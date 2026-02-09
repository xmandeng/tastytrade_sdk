"""Unit tests for reconnection workflow primitives (TT-24)."""

import asyncio
from unittest.mock import patch

import pytest

from tastytrade.config.enumerations import ReconnectReason
from tastytrade.connections.sockets import ConnectionState, DXLinkManager


@pytest.fixture
def dxlink_manager():
    """Create a DXLinkManager instance for testing."""
    # Use a minimal mock setup to avoid external dependencies
    with patch(
        "tastytrade.connections.sockets.DXLinkManager.__init__", return_value=None
    ):
        manager = DXLinkManager.__new__(DXLinkManager)
        manager.connection_state = ConnectionState.CONNECTED
        manager.last_error = None
        manager.reconnect_reason = None
        manager.reconnect_event = asyncio.Event()
        manager.websocket = None
        manager.router = None
        manager.session = None
        manager.should_reconnect = True
        return manager


def test_trigger_reconnect_sets_error_state(dxlink_manager):
    """Test that trigger_reconnect() sets connection state to ERROR."""
    dxlink_manager.trigger_reconnect(ReconnectReason.AUTH_EXPIRED)

    assert dxlink_manager.connection_state == ConnectionState.ERROR
    assert dxlink_manager.last_error == "auth_expired"
    assert dxlink_manager.reconnect_reason == ReconnectReason.AUTH_EXPIRED
    assert dxlink_manager.reconnect_event.is_set()


def test_trigger_reconnect_with_different_reasons(dxlink_manager):
    """Test trigger_reconnect() with all ReconnectReason values."""
    test_cases = [
        (ReconnectReason.AUTH_EXPIRED, "auth_expired"),
        (ReconnectReason.CONNECTION_DROPPED, "connection_dropped"),
        (ReconnectReason.TIMEOUT, "timeout"),
        (ReconnectReason.MANUAL_TRIGGER, "manual_trigger"),
    ]

    for reason, expected_error in test_cases:
        # Reset state
        dxlink_manager.connection_state = ConnectionState.CONNECTED
        dxlink_manager.reconnect_event.clear()

        # Trigger reconnect
        dxlink_manager.trigger_reconnect(reason)

        # Verify
        assert dxlink_manager.connection_state == ConnectionState.ERROR
        assert dxlink_manager.last_error == expected_error
        assert dxlink_manager.reconnect_reason == reason
        assert dxlink_manager.reconnect_event.is_set()


@pytest.mark.asyncio
async def test_wait_for_reconnect_signal_blocks_until_triggered(dxlink_manager):
    """Test that wait_for_reconnect_signal() blocks until reconnect triggered."""
    # Start waiting for signal
    wait_task = asyncio.create_task(dxlink_manager.wait_for_reconnect_signal())

    # Give it time to start waiting
    await asyncio.sleep(0.01)
    assert not wait_task.done(), "Task should be waiting"

    # Trigger reconnect
    dxlink_manager.trigger_reconnect(ReconnectReason.TIMEOUT)

    # Wait for signal to be processed
    result = await wait_task

    # Verify correct reason returned
    assert result == ReconnectReason.TIMEOUT


@pytest.mark.asyncio
async def test_wait_for_reconnect_signal_clears_event(dxlink_manager):
    """Test that wait_for_reconnect_signal() clears the event after processing."""
    # Trigger reconnect
    dxlink_manager.trigger_reconnect(ReconnectReason.AUTH_EXPIRED)
    assert dxlink_manager.reconnect_event.is_set()

    # Wait for signal
    await dxlink_manager.wait_for_reconnect_signal()

    # Event should be cleared
    assert not dxlink_manager.reconnect_event.is_set()


@pytest.mark.asyncio
async def test_wait_for_reconnect_signal_returns_manual_trigger_if_none(dxlink_manager):
    """Test that MANUAL_TRIGGER is returned if reconnect_reason is None."""
    # Manually set event without using trigger_reconnect
    dxlink_manager.reconnect_reason = None
    dxlink_manager.reconnect_event.set()

    result = await dxlink_manager.wait_for_reconnect_signal()

    assert result == ReconnectReason.MANUAL_TRIGGER


def test_simulate_failure_calls_trigger_reconnect(dxlink_manager):
    """Test that simulate_failure() delegates to trigger_reconnect()."""
    with patch.object(dxlink_manager, "trigger_reconnect") as mock_trigger:
        dxlink_manager.simulate_failure(ReconnectReason.CONNECTION_DROPPED)

        mock_trigger.assert_called_once_with(ReconnectReason.CONNECTION_DROPPED)


def test_simulate_failure_logs_warning(dxlink_manager):
    """Test that simulate_failure() logs a warning."""
    with patch("tastytrade.connections.sockets.logger") as mock_logger:
        dxlink_manager.simulate_failure(ReconnectReason.AUTH_EXPIRED)

        mock_logger.warning.assert_called_once_with(
            "Simulating failure: %s", "auth_expired"
        )


def test_simulate_failure_with_all_reasons(dxlink_manager):
    """Test simulate_failure() with all ReconnectReason values."""
    for reason in ReconnectReason:
        # Reset state
        dxlink_manager.connection_state = ConnectionState.CONNECTED
        dxlink_manager.reconnect_event.clear()

        # Simulate failure
        dxlink_manager.simulate_failure(reason)

        # Verify trigger_reconnect was called
        assert dxlink_manager.connection_state == ConnectionState.ERROR
        assert dxlink_manager.reconnect_reason == reason
        assert dxlink_manager.reconnect_event.is_set()


@pytest.mark.asyncio
async def test_multiple_reconnect_signals_sequential(dxlink_manager):
    """Test multiple reconnect signals processed sequentially."""
    results = []

    async def wait_and_collect():
        for _ in range(3):
            reason = await dxlink_manager.wait_for_reconnect_signal()
            results.append(reason)

    wait_task = asyncio.create_task(wait_and_collect())

    # Trigger multiple reconnects
    await asyncio.sleep(0.01)
    dxlink_manager.trigger_reconnect(ReconnectReason.AUTH_EXPIRED)
    await asyncio.sleep(0.01)
    dxlink_manager.trigger_reconnect(ReconnectReason.CONNECTION_DROPPED)
    await asyncio.sleep(0.01)
    dxlink_manager.trigger_reconnect(ReconnectReason.TIMEOUT)

    await wait_task

    assert results == [
        ReconnectReason.AUTH_EXPIRED,
        ReconnectReason.CONNECTION_DROPPED,
        ReconnectReason.TIMEOUT,
    ]


@pytest.mark.asyncio
async def test_reconnect_event_multiple_waiters(dxlink_manager):
    """Test that multiple tasks can wait for reconnect signal."""
    results = []

    async def waiter(name):
        reason = await dxlink_manager.wait_for_reconnect_signal()
        results.append((name, reason))

    # Start multiple waiters
    wait_tasks = [
        asyncio.create_task(waiter("waiter1")),
        asyncio.create_task(waiter("waiter2")),
        asyncio.create_task(waiter("waiter3")),
    ]

    await asyncio.sleep(0.01)

    # Trigger reconnect
    dxlink_manager.trigger_reconnect(ReconnectReason.TIMEOUT)

    # Wait for all tasks
    await asyncio.gather(*wait_tasks)

    # All waiters should have received the signal
    assert len(results) >= 1  # At least one should receive it
    # Note: Event.set() wakes all waiters, but only first clears it


def test_reconnect_preserves_previous_state_before_error(dxlink_manager):
    """Test that we can track state before error was set."""
    # Set various states
    dxlink_manager.connection_state = ConnectionState.CONNECTED

    # Trigger reconnect
    previous_state = dxlink_manager.connection_state
    dxlink_manager.trigger_reconnect(ReconnectReason.AUTH_EXPIRED)

    # Should now be ERROR, but we captured previous state
    assert previous_state == ConnectionState.CONNECTED
    assert dxlink_manager.connection_state == ConnectionState.ERROR
