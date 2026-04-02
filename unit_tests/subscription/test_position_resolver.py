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


def make_position_json(
    symbol: str,
    streamer: str,
    qty: str = "1.0",
    underlying: str | None = None,
) -> str:
    data: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": symbol,
        "instrument-type": "Equity Option",
        "quantity": qty,
        "quantity-direction": "Long" if float(qty) > 0 else "Zero",
        "streamer-symbol": streamer,
    }
    if underlying is not None:
        data["underlying-symbol"] = underlying
    return json.dumps(data)


def make_instrument_json(symbol: str, streamer: str) -> str:
    return json.dumps({"symbol": symbol, "streamer-symbol": streamer})


@pytest.fixture
def mock_redis() -> AsyncMock:
    mock = AsyncMock()
    # Default: no instrument found for underlying lookup
    mock.hget.return_value = None
    return mock


@pytest.fixture
def mock_dxlink() -> AsyncMock:
    mock = AsyncMock()
    mock.subscribe = AsyncMock()
    mock.unsubscribe = AsyncMock()
    return mock


@pytest.fixture
def mock_candle_subscriber() -> AsyncMock:
    mock = AsyncMock()
    mock.subscribe_to_candles = AsyncMock()
    mock.unsubscribe_to_candles = AsyncMock()
    return mock


@pytest.fixture
def resolver(mock_redis: AsyncMock, mock_dxlink: AsyncMock) -> PositionSymbolResolver:
    r = PositionSymbolResolver.__new__(PositionSymbolResolver)
    r.redis = mock_redis
    r.dxlink = mock_dxlink
    r.candle_subscriber = None
    r.intervals = []
    r.subscribed_symbols = set[str]()
    r.subscribed_candle_symbols = set[str]()
    return r


@pytest.fixture
def resolver_with_candles(
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
    mock_candle_subscriber: AsyncMock,
) -> PositionSymbolResolver:
    r = PositionSymbolResolver.__new__(PositionSymbolResolver)
    r.redis = mock_redis
    r.dxlink = mock_dxlink
    r.candle_subscriber = mock_candle_subscriber
    r.intervals = ["1d", "1h", "m"]
    r.subscribed_symbols = set[str]()
    r.subscribed_candle_symbols = set[str]()
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
async def test_resolve_subscribes_underlying_via_instrument_lookup(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    """Underlying subscription uses streamer-symbol from instrument record."""
    mock_redis.hgetall.return_value = {
        b".SPY260402P666": make_position_json(
            "SPY 260402P666", ".SPY260402P666", underlying="SPY"
        ).encode(),
    }
    mock_redis.hget.return_value = make_instrument_json("SPY", "SPY").encode()
    await resolver.resolve()
    subscribed = set(mock_dxlink.subscribe.call_args[0][0])
    assert subscribed == {".SPY260402P666", "SPY"}


@pytest.mark.asyncio
async def test_resolve_subscribes_exchange_qualified_futures_underlying(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    """Futures underlying resolves to exchange-qualified streamer-symbol."""
    mock_redis.hgetall.return_value = {
        b"./OZBK26P111:XCBT": make_position_json(
            "./ZBM6 OZBK6 260424P111", "./OZBK26P111:XCBT", underlying="/ZBM6"
        ).encode(),
    }
    mock_redis.hget.return_value = make_instrument_json("/ZBM6", "/ZBM26:XCBT").encode()
    await resolver.resolve()
    subscribed = set(mock_dxlink.subscribe.call_args[0][0])
    assert subscribed == {"./OZBK26P111:XCBT", "/ZBM26:XCBT"}


@pytest.mark.asyncio
async def test_resolve_skips_underlying_without_instrument(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    """Underlying with no instrument record is not subscribed."""
    mock_redis.hgetall.return_value = {
        b"./LOK26P70:XNYM": make_position_json(
            "./CLK6 LOK6 260416P70", "./LOK26P70:XNYM", underlying="/CLK6"
        ).encode(),
    }
    mock_redis.hget.return_value = None
    await resolver.resolve()
    subscribed = set(mock_dxlink.subscribe.call_args[0][0])
    assert subscribed == {"./LOK26P70:XNYM"}
    assert "/CLK6" not in subscribed


@pytest.mark.asyncio
async def test_resolve_deduplicates_underlying(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    """Multiple options on same underlying = one underlying subscription."""
    mock_redis.hgetall.return_value = {
        b".SPY260402P666": make_position_json(
            "SPY 260402P666", ".SPY260402P666", underlying="SPY"
        ).encode(),
        b".SPY260402C700": make_position_json(
            "SPY 260402C700", ".SPY260402C700", underlying="SPY"
        ).encode(),
    }
    mock_redis.hget.return_value = make_instrument_json("SPY", "SPY").encode()
    await resolver.resolve()
    subscribed = set(mock_dxlink.subscribe.call_args[0][0])
    assert subscribed == {".SPY260402P666", ".SPY260402C700", "SPY"}


@pytest.mark.asyncio
async def test_resolve_unsubscribes_underlying_when_all_options_closed(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_dxlink: AsyncMock,
) -> None:
    resolver.subscribed_symbols = {".SPY260402P666", "SPY"}
    mock_redis.hgetall.return_value = {}
    await resolver.resolve()
    unsubscribed = set(mock_dxlink.unsubscribe.call_args[0][0])
    assert unsubscribed == {".SPY260402P666", "SPY"}


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


# ---------------------------------------------------------------------------
# Candle subscription tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_subscribes_candles_for_underlyings(
    resolver_with_candles: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_candle_subscriber: AsyncMock,
) -> None:
    """Resolved underlyings get candle subscriptions for all intervals."""
    mock_redis.hgetall.return_value = {
        b".SPY260402P666": make_position_json(
            "SPY 260402P666", ".SPY260402P666", underlying="SPY"
        ).encode(),
    }
    mock_redis.hget.return_value = make_instrument_json("SPY", "SPY").encode()
    await resolver_with_candles.resolve()

    assert mock_candle_subscriber.subscribe_to_candles.call_count == 3
    subscribed_intervals = [
        call.args[1]
        for call in mock_candle_subscriber.subscribe_to_candles.call_args_list
    ]
    assert sorted(subscribed_intervals) == ["1d", "1h", "m"]
    assert resolver_with_candles.subscribed_candle_symbols == {"SPY"}


@pytest.mark.asyncio
async def test_resolve_unsubscribes_candles_when_positions_closed(
    resolver_with_candles: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_candle_subscriber: AsyncMock,
) -> None:
    """Candle subscriptions removed when all positions for an underlying close."""
    resolver_with_candles.subscribed_symbols = {".SPY260402P666", "SPY"}
    resolver_with_candles.subscribed_candle_symbols = {"SPY"}
    mock_redis.hgetall.return_value = {}
    await resolver_with_candles.resolve()

    assert mock_candle_subscriber.unsubscribe_to_candles.call_count == 3
    unsub_symbols = [
        call.args[0]
        for call in mock_candle_subscriber.unsubscribe_to_candles.call_args_list
    ]
    assert sorted(unsub_symbols) == ["SPY{=1d}", "SPY{=1h}", "SPY{=m}"]
    assert resolver_with_candles.subscribed_candle_symbols == set()


@pytest.mark.asyncio
async def test_resolve_no_candle_change_when_underlyings_unchanged(
    resolver_with_candles: PositionSymbolResolver,
    mock_redis: AsyncMock,
    mock_candle_subscriber: AsyncMock,
) -> None:
    """No candle subscribe/unsubscribe if underlyings haven't changed."""
    resolver_with_candles.subscribed_symbols = {".SPY260402P666", "SPY"}
    resolver_with_candles.subscribed_candle_symbols = {"SPY"}
    mock_redis.hgetall.return_value = {
        b".SPY260402P666": make_position_json(
            "SPY 260402P666", ".SPY260402P666", underlying="SPY"
        ).encode(),
    }
    mock_redis.hget.return_value = make_instrument_json("SPY", "SPY").encode()
    await resolver_with_candles.resolve()

    mock_candle_subscriber.subscribe_to_candles.assert_not_called()
    mock_candle_subscriber.unsubscribe_to_candles.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_no_candles_without_candle_subscriber(
    resolver: PositionSymbolResolver,
    mock_redis: AsyncMock,
) -> None:
    """Without candle_subscriber, no candle operations happen."""
    mock_redis.hgetall.return_value = {
        b".SPY260402P666": make_position_json(
            "SPY 260402P666", ".SPY260402P666", underlying="SPY"
        ).encode(),
    }
    mock_redis.hget.return_value = make_instrument_json("SPY", "SPY").encode()
    await resolver.resolve()
    assert resolver.subscribed_candle_symbols == set()
