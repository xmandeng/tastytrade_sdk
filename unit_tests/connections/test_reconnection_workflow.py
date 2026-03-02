"""Unit tests for reconnection workflow primitives (TT-24, TT-64)."""

import asyncio
from unittest.mock import patch

import pytest

from tastytrade.config.enumerations import ReconnectReason
from tastytrade.connections.signals import ReconnectSignal
from tastytrade.connections.sockets import ConnectionState, DXLinkManager


# === ReconnectSignal tests ===


def test_signal_trigger_sets_event_and_reason():
    """Test that trigger() sets the asyncio event and stores the reason."""
    signal = ReconnectSignal()
    signal.trigger(ReconnectReason.AUTH_EXPIRED)

    assert signal.event.is_set()
    assert signal.reason == ReconnectReason.AUTH_EXPIRED


def test_signal_trigger_with_all_reasons():
    """Test trigger() with all ReconnectReason values."""
    signal = ReconnectSignal()

    for reason in ReconnectReason:
        signal.reset()
        signal.trigger(reason)

        assert signal.event.is_set()
        assert signal.reason == reason


@pytest.mark.asyncio
async def test_signal_wait_blocks_until_triggered():
    """Test that wait() blocks until trigger() is called."""
    signal = ReconnectSignal()
    wait_task = asyncio.create_task(signal.wait())

    await asyncio.sleep(0.01)
    assert not wait_task.done(), "Task should be waiting"

    signal.trigger(ReconnectReason.TIMEOUT)

    result = await wait_task
    assert result == ReconnectReason.TIMEOUT


@pytest.mark.asyncio
async def test_signal_wait_clears_event():
    """Test that wait() clears the event after returning."""
    signal = ReconnectSignal()
    signal.trigger(ReconnectReason.AUTH_EXPIRED)
    assert signal.event.is_set()

    await signal.wait()
    assert not signal.event.is_set()


@pytest.mark.asyncio
async def test_signal_wait_returns_manual_trigger_if_none():
    """Test that MANUAL_TRIGGER is returned if reason is None."""
    signal = ReconnectSignal()
    signal.reason = None
    signal.event.set()

    result = await signal.wait()
    assert result == ReconnectReason.MANUAL_TRIGGER


def test_signal_reset_clears_state():
    """Test that reset() clears both event and reason."""
    signal = ReconnectSignal()
    signal.trigger(ReconnectReason.CONNECTION_DROPPED)

    signal.reset()

    assert not signal.event.is_set()
    assert signal.reason is None


@pytest.mark.asyncio
async def test_signal_multiple_sequential_triggers():
    """Test multiple sequential trigger/wait cycles."""
    signal = ReconnectSignal()
    results = []

    async def wait_and_collect():
        for _ in range(3):
            reason = await signal.wait()
            results.append(reason)

    wait_task = asyncio.create_task(wait_and_collect())

    await asyncio.sleep(0.01)
    signal.trigger(ReconnectReason.AUTH_EXPIRED)
    await asyncio.sleep(0.01)
    signal.trigger(ReconnectReason.CONNECTION_DROPPED)
    await asyncio.sleep(0.01)
    signal.trigger(ReconnectReason.TIMEOUT)

    await wait_task

    assert results == [
        ReconnectReason.AUTH_EXPIRED,
        ReconnectReason.CONNECTION_DROPPED,
        ReconnectReason.TIMEOUT,
    ]


# === DXLinkManager.inject_connection_dropped tests ===


@pytest.fixture
def dxlink_manager():
    """Create a DXLinkManager instance for testing."""
    with patch(
        "tastytrade.connections.sockets.DXLinkManager.__init__", return_value=None
    ):
        manager = DXLinkManager.__new__(DXLinkManager)
        manager.connection_state = ConnectionState.CONNECTED
        manager.last_error = None
        manager.websocket = None
        manager.router = None
        manager.session = None
        manager.should_reconnect = True
        manager.queues = {0: asyncio.Queue()}
        manager.reconnect_signal = ReconnectSignal()
        return manager


@pytest.mark.asyncio
async def test_inject_connection_dropped_sets_error_state(dxlink_manager):
    """Test that inject_connection_dropped() sets connection state to ERROR."""
    await dxlink_manager.inject_connection_dropped(ReconnectReason.CONNECTION_DROPPED)

    assert dxlink_manager.connection_state == ConnectionState.ERROR
    assert dxlink_manager.last_error == "connection_dropped"


@pytest.mark.asyncio
async def test_inject_connection_dropped_puts_message_in_queue(dxlink_manager):
    """Test that inject_connection_dropped() places a message in Queue[0]."""
    await dxlink_manager.inject_connection_dropped(ReconnectReason.AUTH_EXPIRED)

    assert not dxlink_manager.queues[0].empty()
    message = dxlink_manager.queues[0].get_nowait()

    assert message["type"] == "CONNECTION_DROPPED"
    assert message["channel"] == 0
    assert message["reason"] == "auth_expired"


@pytest.mark.asyncio
async def test_inject_connection_dropped_with_all_reasons(dxlink_manager):
    """Test inject_connection_dropped() with all ReconnectReason values."""
    for reason in ReconnectReason:
        dxlink_manager.connection_state = ConnectionState.CONNECTED
        await dxlink_manager.inject_connection_dropped(reason)

        assert dxlink_manager.connection_state == ConnectionState.ERROR
        assert dxlink_manager.last_error == reason.value

        message = dxlink_manager.queues[0].get_nowait()
        assert message["type"] == "CONNECTION_DROPPED"
        assert message["reason"] == reason.value


@pytest.mark.asyncio
async def test_simulate_failure_delegates_to_inject(dxlink_manager):
    """Test that simulate_failure() delegates to inject_connection_dropped()."""
    await dxlink_manager.simulate_failure(ReconnectReason.CONNECTION_DROPPED)

    assert dxlink_manager.connection_state == ConnectionState.ERROR
    message = dxlink_manager.queues[0].get_nowait()
    assert message["type"] == "CONNECTION_DROPPED"
    assert message["reason"] == "connection_dropped"


@pytest.mark.asyncio
async def test_simulate_failure_logs_warning(dxlink_manager):
    """Test that simulate_failure() logs a warning."""
    with patch("tastytrade.connections.sockets.logger") as mock_logger:
        await dxlink_manager.simulate_failure(ReconnectReason.AUTH_EXPIRED)

        mock_logger.warning.assert_called_once_with(
            "Simulating failure: %s", "auth_expired"
        )


# === End-to-end: Queue[0] -> ControlHandler -> ReconnectSignal ===


@pytest.mark.asyncio
async def test_end_to_end_connection_dropped_flow():
    """Test the full pipeline: inject -> Queue[0] -> ControlHandler -> ReconnectSignal."""
    from tastytrade.messaging.handlers import ControlHandler

    signal = ReconnectSignal()
    handler = ControlHandler(reconnect_signal=signal)

    # Simulate what inject_connection_dropped puts into Queue[0]
    from tastytrade.messaging.models.messages import Message

    message = Message(
        type="CONNECTION_DROPPED",
        channel=0,
        headers={"type": "CONNECTION_DROPPED", "channel": 0, "reason": "auth_expired"},
        data={},
    )

    await handler.handle_message(message)

    # Signal should be triggered with the correct reason
    assert signal.event.is_set()
    assert signal.reason == ReconnectReason.AUTH_EXPIRED


@pytest.mark.asyncio
async def test_end_to_end_error_timeout_flow():
    """Test pipeline: ERROR message -> ControlHandler -> ReconnectSignal."""
    from tastytrade.messaging.handlers import ControlHandler

    signal = ReconnectSignal()
    handler = ControlHandler(reconnect_signal=signal)

    from tastytrade.messaging.models.messages import Message

    message = Message(
        type="ERROR",
        channel=0,
        headers={"type": "ERROR", "error": "TIMEOUT", "message": "session timeout"},
        data={},
    )

    await handler.handle_message(message)

    assert signal.event.is_set()
    assert signal.reason == ReconnectReason.TIMEOUT


def test_reconnect_preserves_previous_state_before_error(dxlink_manager):
    """Test that we can track state before error was set."""
    dxlink_manager.connection_state = ConnectionState.CONNECTED

    previous_state = dxlink_manager.connection_state
    # Directly set error state (as inject_connection_dropped would)
    dxlink_manager.connection_state = ConnectionState.ERROR

    assert previous_state == ConnectionState.CONNECTED
    assert dxlink_manager.connection_state == ConnectionState.ERROR
