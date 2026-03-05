"""Unit tests for get_reconnect_start — calendar-day lookback on reconnect."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

from tastytrade.subscription.orchestrator import get_reconnect_start


SYMBOLS = ["AAPL", "SPY"]
INTERVALS = ["1d", "1h"]


@pytest.mark.asyncio
async def test_no_subscriptions_returns_fallback():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(return_value={})
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    assert result == fallback


@pytest.mark.asyncio
async def test_rounds_to_start_of_calendar_day():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "AAPL": {"last_update": "2026-03-04T14:30:00+00:00"},
            "SPY": {"last_update": "2026-03-04T16:45:00+00:00"},
        }
    )
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    assert result == datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_uses_earliest_last_update():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "AAPL": {"last_update": "2026-03-03T08:00:00+00:00"},
            "SPY": {"last_update": "2026-03-04T16:00:00+00:00"},
        }
    )
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    # Earliest is AAPL on Mar 3, so midnight Mar 3
    assert result == datetime(2026, 3, 3, 0, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_ignores_symbols_not_in_session():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "AAPL": {"last_update": "2026-03-04T14:00:00+00:00"},
            "TSLA": {"last_update": "2026-02-01T10:00:00+00:00"},
            "BTC/USD": {"last_update": "2026-01-15T08:00:00+00:00"},
        }
    )
    fallback = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    # TSLA and BTC/USD are not in SYMBOLS, so only AAPL is considered
    assert result == datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_includes_candle_keys():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "AAPL": {"last_update": "2026-03-04T14:00:00+00:00"},
            "AAPL{=d}": {"last_update": "2026-03-03T20:00:00+00:00"},
        }
    )
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    # Candle key AAPL{=d} is older, so midnight Mar 3
    assert result == datetime(2026, 3, 3, 0, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_skips_entries_without_last_update():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "AAPL": {},
            "SPY": {"last_update": "2026-03-04T10:00:00+00:00"},
        }
    )
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    assert result == datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_skips_invalid_timestamps():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "AAPL": {"last_update": "not-a-date"},
            "SPY": {"last_update": "2026-03-04T10:00:00+00:00"},
        }
    )
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    assert result == datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_no_matching_symbols_returns_fallback():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "TSLA": {"last_update": "2026-03-04T10:00:00+00:00"},
            "BTC/USD": {"last_update": "2026-03-04T12:00:00+00:00"},
        }
    )
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    assert result == fallback


@pytest.mark.asyncio
async def test_non_dict_subscription_data_skipped():
    store = Mock()
    store.get_all_subscriptions = AsyncMock(
        return_value={
            "AAPL": "just_a_string",
            "SPY": {"last_update": "2026-03-04T10:00:00+00:00"},
        }
    )
    fallback = datetime(2026, 2, 1, tzinfo=timezone.utc)

    result = await get_reconnect_start(
        store, symbols=SYMBOLS, intervals=INTERVALS, fallback=fallback
    )

    assert result == datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)
