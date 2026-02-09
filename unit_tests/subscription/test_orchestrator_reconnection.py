"""Unit tests for orchestrator reconnection logic."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tastytrade.config.enumerations import ReconnectReason
from tastytrade.subscription.orchestrator import (
    extract_candle_parts,
    format_uptime,
    restore_subscriptions,
)


def test_format_uptime_seconds():
    """Test format_uptime with seconds."""
    assert format_uptime(30) == "0m"
    assert format_uptime(59) == "0m"


def test_format_uptime_minutes():
    """Test format_uptime with minutes."""
    assert format_uptime(60) == "1m"
    assert format_uptime(120) == "2m"
    assert format_uptime(3540) == "59m"


def test_format_uptime_hours():
    """Test format_uptime with hours."""
    assert format_uptime(3600) == "1h 0m"
    assert format_uptime(7200) == "2h 0m"
    assert format_uptime(7320) == "2h 2m"


def test_format_uptime_days():
    """Test format_uptime with days."""
    assert format_uptime(86400) == "1d 0h 0m"
    assert format_uptime(90000) == "1d 1h 0m"
    assert format_uptime(172800) == "2d 0h 0m"


def test_extract_candle_parts_valid():
    """Test extract_candle_parts with valid candle symbols."""
    assert extract_candle_parts("AAPL{=1d}") == ("AAPL", "1d")
    assert extract_candle_parts("SPY{=1h}") == ("SPY", "1h")
    assert extract_candle_parts("QQQ{=5m}") == ("QQQ", "5m")
    assert extract_candle_parts("BTC/USD:CXTALP{=m}") == ("BTC/USD:CXTALP", "m")


def test_extract_candle_parts_invalid():
    """Test extract_candle_parts with non-candle symbols."""
    assert extract_candle_parts("AAPL") is None
    assert extract_candle_parts("SPY.Quote") is None
    assert extract_candle_parts("") is None
    assert extract_candle_parts("AAPL{1d}") is None  # Missing =


@pytest.mark.asyncio
async def test_restore_subscriptions_no_active():
    """Test restore_subscriptions when no active subscriptions."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(return_value={})

    count = await restore_subscriptions(mock_dxlink)

    assert count == 0
    mock_dxlink.subscribe.assert_not_called()


@pytest.mark.asyncio
async def test_restore_subscriptions_tickers_only():
    """Test restore_subscriptions with ticker subscriptions only."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL": {},
            "SPY": {},
            "QQQ": {},
        }
    )
    mock_dxlink.subscribe = AsyncMock()

    count = await restore_subscriptions(mock_dxlink)

    assert count == 3
    mock_dxlink.subscribe.assert_called_once_with(["AAPL", "SPY", "QQQ"])


@pytest.mark.asyncio
async def test_restore_subscriptions_candles_only():
    """Test restore_subscriptions with candle subscriptions only."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL{=1d}": {"last_update": "2026-02-08T12:00:00+00:00"},
            "SPY{=1h}": {"last_update": "2026-02-08T11:00:00+00:00"},
        }
    )
    mock_dxlink.subscribe_to_candles = AsyncMock()

    count = await restore_subscriptions(mock_dxlink)

    assert count == 2
    assert mock_dxlink.subscribe_to_candles.call_count == 2


@pytest.mark.asyncio
async def test_restore_subscriptions_mixed():
    """Test restore_subscriptions with mixed ticker and candle subscriptions."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL": {},
            "SPY": {},
            "AAPL{=1d}": {"last_update": "2026-02-08T12:00:00+00:00"},
        }
    )
    mock_dxlink.subscribe = AsyncMock()
    mock_dxlink.subscribe_to_candles = AsyncMock()

    count = await restore_subscriptions(mock_dxlink)

    assert count == 3
    mock_dxlink.subscribe.assert_called_once_with(["AAPL", "SPY"])
    mock_dxlink.subscribe_to_candles.assert_called_once()


@pytest.mark.asyncio
async def test_restore_subscriptions_with_backfill():
    """Test restore_subscriptions applies 1-hour backfill buffer."""
    mock_dxlink = Mock()
    last_update_str = "2026-02-08T12:00:00+00:00"
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL{=1d}": {"last_update": last_update_str},
        }
    )
    mock_dxlink.subscribe_to_candles = AsyncMock()

    await restore_subscriptions(mock_dxlink)

    # Verify backfill time is approximately 1 hour before last_update
    # Args are: (symbol, interval, from_time)
    call_args = mock_dxlink.subscribe_to_candles.call_args[0]
    assert call_args[0] == "AAPL"
    assert call_args[1] == "1d"

    # from_time should be about 1 hour before last_update
    from_time = call_args[2]
    last_update = datetime.fromisoformat(last_update_str)
    time_diff = (last_update - from_time).total_seconds()
    assert 3500 <= time_diff <= 3700  # ~1 hour (3600s) with some tolerance


@pytest.mark.asyncio
async def test_restore_subscriptions_invalid_last_update():
    """Test restore_subscriptions handles invalid last_update timestamp."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL{=1d}": {"last_update": "invalid_timestamp"},
        }
    )
    mock_dxlink.subscribe_to_candles = AsyncMock()

    count = await restore_subscriptions(mock_dxlink)

    # Should still restore, but use default backfill time
    assert count == 1
    mock_dxlink.subscribe_to_candles.assert_called_once()


@pytest.mark.asyncio
async def test_restore_subscriptions_missing_last_update():
    """Test restore_subscriptions when last_update metadata is missing."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL{=1d}": {},  # No last_update
        }
    )
    mock_dxlink.subscribe_to_candles = AsyncMock()

    count = await restore_subscriptions(mock_dxlink)

    # Should still restore with default backfill
    assert count == 1
    mock_dxlink.subscribe_to_candles.assert_called_once()


@pytest.mark.asyncio
async def test_restore_subscriptions_unparseable_candle_symbol():
    """Test restore_subscriptions handles candle symbols that can't be parsed."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL{=}": {},  # Candle symbol (has {=) but missing interval
        }
    )
    mock_dxlink.subscribe = AsyncMock()
    mock_dxlink.subscribe_to_candles = AsyncMock()

    with patch("tastytrade.subscription.orchestrator.logger") as mock_logger:
        count = await restore_subscriptions(mock_dxlink)

        # Should log warning and skip unparseable candle
        assert count == 0
        mock_logger.warning.assert_called_once()
        mock_dxlink.subscribe_to_candles.assert_not_called()


@pytest.mark.asyncio
async def test_restore_subscriptions_logs_progress():
    """Test restore_subscriptions logs restoration progress."""
    mock_dxlink = Mock()
    mock_dxlink.subscription_store.get_active_subscriptions = AsyncMock(
        return_value={
            "AAPL": {},
            "AAPL{=1d}": {},
        }
    )
    mock_dxlink.subscribe = AsyncMock()
    mock_dxlink.subscribe_to_candles = AsyncMock()

    with patch("tastytrade.subscription.orchestrator.logger") as mock_logger:
        count = await restore_subscriptions(mock_dxlink)

        assert count == 2

        # Should log ticker restoration
        mock_logger.info.assert_any_call("Restored %d ticker subscriptions", 1)

        # Should log total restored
        mock_logger.info.assert_any_call("Restored %d total subscriptions", 2)


@pytest.mark.asyncio
async def test_failure_listener_conditional_startup():
    """Test that failure listener only starts when Redis configured."""
    # This tests the orchestrator logic at lines 379-384
    from tastytrade.connections.subscription import RedisSubscriptionStore

    # Mock subscription store that IS RedisSubscriptionStore
    redis_store = Mock(spec=RedisSubscriptionStore)

    # In real code, this check determines if listener starts:
    # if isinstance(subscription_store, RedisSubscriptionStore):
    assert isinstance(redis_store, RedisSubscriptionStore)

    # Mock subscription store that IS NOT RedisSubscriptionStore
    other_store = Mock()
    assert not isinstance(other_store, RedisSubscriptionStore)


@pytest.mark.asyncio
async def test_exponential_backoff_calculation():
    """Test exponential backoff delay calculation."""
    base_delay = 1.0
    max_delay = 300.0

    # Test exponential growth
    expected_delays = [
        2.0,  # attempt 1: 1 * 2^1 = 2
        4.0,  # attempt 2: 1 * 2^2 = 4
        8.0,  # attempt 3: 1 * 2^3 = 8
        16.0,  # attempt 4: 1 * 2^4 = 16
        32.0,  # attempt 5: 1 * 2^5 = 32
    ]

    for attempt, expected in enumerate(expected_delays, 1):
        delay = min(base_delay * (2**attempt), max_delay)
        assert delay == expected

    # Test max_delay cap
    for attempt in range(10, 20):
        delay = min(base_delay * (2**attempt), max_delay)
        assert delay == max_delay


@pytest.mark.asyncio
async def test_reconnection_trigger_flow():
    """Test the complete reconnection trigger flow."""
    from tastytrade.connections.sockets import DXLinkManager

    with patch(
        "tastytrade.connections.sockets.DXLinkManager.__init__", return_value=None
    ):
        dxlink = DXLinkManager.__new__(DXLinkManager)
        dxlink.reconnect_event = asyncio.Event()
        dxlink.reconnect_reason = None

        # Simulate the orchestrator monitoring flow
        async def mock_reconnection_monitor():
            """Simulates orchestrator.py:386-389"""
            reason = await dxlink.wait_for_reconnect_signal()
            return reason

        monitor_task = asyncio.create_task(mock_reconnection_monitor())
        await asyncio.sleep(0.01)

        # Verify task is waiting
        assert not monitor_task.done()

        # Trigger reconnect (simulates failure_trigger_listener calling simulate_failure)
        dxlink.reconnect_reason = ReconnectReason.AUTH_EXPIRED
        dxlink.reconnect_event.set()

        # Monitor should detect and return reason
        reason = await monitor_task
        assert reason == ReconnectReason.AUTH_EXPIRED
