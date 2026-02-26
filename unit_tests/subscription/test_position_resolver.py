"""Tests for PositionSymbolResolver -- diffs position symbols against subscriptions."""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tastytrade.subscription.resolver import PositionSymbolResolver


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
