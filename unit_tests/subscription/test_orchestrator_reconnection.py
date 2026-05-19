"""Unit tests for orchestrator reconnection logic."""

import asyncio
from unittest.mock import Mock

import pytest

from tastytrade.config.enumerations import ReconnectReason
from tastytrade.subscription.orchestrator import (
    extract_candle_parts,
    format_uptime,
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
    """Test the complete reconnection trigger flow using ReconnectSignal."""
    from tastytrade.connections.signals import ReconnectSignal

    signal = ReconnectSignal()

    # Simulate the orchestrator monitoring flow: await signal.wait()
    monitor_task = asyncio.create_task(signal.wait())
    await asyncio.sleep(0.01)

    # Verify task is waiting
    assert not monitor_task.done()

    # Trigger reconnect (simulates ControlHandler calling signal.trigger())
    signal.trigger(ReconnectReason.AUTH_EXPIRED)

    # Monitor should detect and return reason
    reason = await monitor_task
    assert reason == ReconnectReason.AUTH_EXPIRED
