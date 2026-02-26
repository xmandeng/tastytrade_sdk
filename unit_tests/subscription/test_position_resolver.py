"""Tests for PositionSymbolResolver -- event-driven position-to-subscription management."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.subscription.resolver import (
    POSITION_EVENTS_CHANNEL,
    PositionSymbolResolver,
)


def make_position_json(symbol: str, streamer: str, qty: str = "1.0") -> str:
    data: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": symbol,
        "instrument-type": "Equity Option",
        "quantity": qty,
        "quantity-direction": "Long" if float(qty) > 0 else "Zero",
        "streamer-symbol": streamer,
    }
    return json.dumps(data)


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_dxlink() -> AsyncMock:
    mock = AsyncMock()
    mock.subscribe = AsyncMock()
    mock.unsubscribe = AsyncMock()
    return mock


@pytest.fixture
def resolver(mock_redis: AsyncMock, mock_dxlink: AsyncMock) -> PositionSymbolResolver:
    r = PositionSymbolResolver.__new__(PositionSymbolResolver)
    r.redis = mock_redis
    r.dxlink = mock_dxlink
    r.subscribed_symbols: set[str] = set()
    return r


@pytest.mark.asyncio
async def test_resolve_subscribes_new_symbols(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
        b".SPY260402P666": make_position_json(
            "SPY 260402P666", ".SPY260402P666"
        ).encode(),
    }
    await resolver.resolve()
    mock_dxlink.subscribe.assert_called_once()
    subscribed = set(mock_dxlink.subscribe.call_args[0][0])
    assert subscribed == {"SPY", ".SPY260402P666"}


@pytest.mark.asyncio
async def test_resolve_unsubscribes_closed_positions(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    resolver.subscribed_symbols = {"SPY", ".SPY260402P666"}
    # Only SPY remains in Redis
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
    }
    await resolver.resolve()
    mock_dxlink.unsubscribe.assert_called_once()
    unsubscribed = set(mock_dxlink.unsubscribe.call_args[0][0])
    assert unsubscribed == {".SPY260402P666"}


@pytest.mark.asyncio
async def test_resolve_no_change_no_calls(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    resolver.subscribed_symbols = {"SPY"}
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
    }
    await resolver.resolve()
    mock_dxlink.subscribe.assert_not_called()
    mock_dxlink.unsubscribe.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_updates_subscribed_set(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
    }
    await resolver.resolve()
    assert resolver.subscribed_symbols == {"SPY"}


@pytest.mark.asyncio
async def test_listen_does_initial_resolve_then_reacts_to_events(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    """listen() should resolve once on startup, then resolve on each pub/sub message."""
    # Simulate pub/sub — pubsub() is synchronous in redis.asyncio
    mock_pubsub = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    position_msg = make_position_json("QQQ", "QQQ")

    async def fake_listen():  # type: ignore[no-untyped-def]
        yield {"type": "subscribe", "data": 1}
        yield {"type": "message", "data": position_msg.encode()}
        raise asyncio.CancelledError()

    mock_pubsub.listen = MagicMock(return_value=fake_listen())

    # Initial resolve finds SPY; second resolve (after event) sees SPY + QQQ
    mock_redis.hgetall.side_effect = [
        {b"SPY": make_position_json("SPY", "SPY").encode()},
        {
            b"SPY": make_position_json("SPY", "SPY").encode(),
            b"QQQ": make_position_json("QQQ", "QQQ").encode(),
        },
    ]

    await resolver.listen()

    mock_pubsub.subscribe.assert_called_once_with(POSITION_EVENTS_CHANNEL)
    assert mock_redis.hgetall.call_count == 2
    assert mock_dxlink.subscribe.call_count == 2
    mock_pubsub.unsubscribe.assert_called_once_with(POSITION_EVENTS_CHANNEL)
    mock_pubsub.close.assert_called_once()


@pytest.mark.asyncio
async def test_listen_continues_on_resolve_error(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    """listen() should log errors from resolve but keep listening."""
    mock_redis.hgetall.return_value = {}

    mock_pubsub = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    async def fake_listen():  # type: ignore[no-untyped-def]
        yield {"type": "message", "data": b"{}"}
        yield {"type": "message", "data": b"{}"}
        raise asyncio.CancelledError()

    mock_pubsub.listen = MagicMock(return_value=fake_listen())

    original_resolve = resolver.resolve
    call_count = 0

    async def flaky_resolve() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # First event handler fails
            raise ConnectionError("Redis gone")
        await original_resolve()

    resolver.resolve = flaky_resolve  # type: ignore[assignment]

    await resolver.listen()

    # Three resolve calls: initial + 2 events (one errored, one succeeded)
    assert call_count == 3
