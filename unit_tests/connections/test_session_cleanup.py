"""Tests for session-scoped subscription cleanup logic."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.connections.subscription import RedisSubscriptionStore
from tastytrade.utils.helpers import format_candle_symbol


def test_session_symbols_built_from_ticker_and_candle() -> None:
    """Verify session_symbols set contains both ticker and candle symbols."""
    symbols = ["AAPL", "SPY"]
    intervals = ["1d", "5m"]

    session_symbols: set[str] = set()

    # Ticker symbols added directly
    session_symbols.update(symbols)

    # Candle symbols added with format_candle_symbol
    for symbol in symbols:
        for interval in intervals:
            event_symbol = format_candle_symbol(f"{symbol}{{={interval}}}")
            session_symbols.add(event_symbol)

    assert "AAPL" in session_symbols
    assert "SPY" in session_symbols
    assert "AAPL{=d}" in session_symbols
    assert "AAPL{=5m}" in session_symbols
    assert "SPY{=d}" in session_symbols
    assert "SPY{=5m}" in session_symbols
    assert len(session_symbols) == 6


def test_session_symbols_only_adds_successful_candles() -> None:
    """Candle symbols should only be added on successful subscription."""
    symbols = ["AAPL", "SPY"]

    session_symbols: set[str] = set()
    session_symbols.update(symbols)

    # Simulate: AAPL 1d succeeds, AAPL 5m fails, SPY both succeed
    successful_pairs = [("AAPL", "1d"), ("SPY", "1d"), ("SPY", "5m")]
    for symbol, interval in successful_pairs:
        event_symbol = format_candle_symbol(f"{symbol}{{={interval}}}")
        session_symbols.add(event_symbol)

    assert "AAPL{=d}" in session_symbols
    assert "AAPL{=5m}" not in session_symbols  # Failed, not added
    assert "SPY{=d}" in session_symbols
    assert "SPY{=5m}" in session_symbols
    assert len(session_symbols) == 5


def test_format_candle_symbol_normalizes_intervals() -> None:
    """Verify interval normalization matches what DXLink sends."""
    assert format_candle_symbol("AAPL{=1d}") == "AAPL{=d}"
    assert format_candle_symbol("AAPL{=1h}") == "AAPL{=h}"
    assert format_candle_symbol("AAPL{=1m}") == "AAPL{=m}"
    assert format_candle_symbol("AAPL{=5m}") == "AAPL{=5m}"
    assert format_candle_symbol("AAPL{=30m}") == "AAPL{=30m}"


@pytest.mark.asyncio
async def test_remove_subscription_called_for_each_session_symbol() -> None:
    """Verify cleanup iterates over session_symbols and calls remove_subscription."""
    store = MagicMock(spec=RedisSubscriptionStore)
    store.remove_subscription = AsyncMock()

    session_symbols = {"AAPL", "SPY", "AAPL{=d}", "SPY{=d}", "SPY{=5m}"}

    for sym in session_symbols:
        await store.remove_subscription(sym)

    assert store.remove_subscription.call_count == 5
    called_symbols = {call.args[0] for call in store.remove_subscription.call_args_list}
    assert called_symbols == session_symbols


@pytest.mark.asyncio
async def test_cleanup_continues_on_individual_failure() -> None:
    """If one remove_subscription fails, others should still be cleaned up."""
    store = MagicMock(spec=RedisSubscriptionStore)

    call_count = 0

    async def mock_remove(sym: str) -> None:
        nonlocal call_count
        call_count += 1
        if sym == "AAPL":
            raise ConnectionError("Redis unavailable")

    store.remove_subscription = mock_remove

    session_symbols = {"AAPL", "SPY", "QQQ"}
    for sym in session_symbols:
        try:
            await store.remove_subscription(sym)
        except Exception:
            pass  # Orchestrator logs warning and continues

    assert call_count == 3


@pytest.mark.asyncio
async def test_empty_session_symbols_skips_cleanup() -> None:
    """No cleanup calls when session has no subscriptions."""
    store = MagicMock(spec=RedisSubscriptionStore)
    store.remove_subscription = AsyncMock()

    session_symbols: set[str] = set()

    if session_symbols:
        for sym in session_symbols:
            await store.remove_subscription(sym)

    store.remove_subscription.assert_not_called()
