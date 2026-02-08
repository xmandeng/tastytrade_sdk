"""Unit tests for Redis pub/sub failure trigger listener (TT-25)."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tastytrade.config.enumerations import ReconnectReason
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.connections.subscription import RedisSubscriptionStore
from tastytrade.subscription.orchestrator import failure_trigger_listener


@pytest.fixture
def mock_redis_store():
    """Create mock RedisSubscriptionStore."""
    store = Mock(spec=RedisSubscriptionStore)
    store.redis = AsyncMock()
    store.redis.pubsub = Mock()
    return store


@pytest.fixture
def mock_dxlink():
    """Create mock DXLinkManager."""
    dxlink = Mock(spec=DXLinkManager)
    dxlink.simulate_failure = Mock()
    return dxlink


@pytest.mark.asyncio
async def test_listener_subscribes_to_correct_channel(mock_redis_store, mock_dxlink):
    """Test that listener subscribes to 'subscription:simulate_failure' channel."""
    # Setup pubsub mock
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()

    # Mock listen to return no messages (immediate exit)
    async def mock_listen():
        return
        yield  # Make it an async generator

    pubsub.listen = mock_listen
    mock_redis_store.redis.pubsub.return_value = pubsub

    # Start listener and cancel immediately
    listener_task = asyncio.create_task(
        failure_trigger_listener(mock_redis_store, mock_dxlink)
    )
    await asyncio.sleep(0.1)
    listener_task.cancel()

    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    # Verify subscription to correct channel
    pubsub.subscribe.assert_called_once_with("subscription:simulate_failure")


@pytest.mark.asyncio
async def test_valid_reconnect_reason_triggers_simulate_failure(
    mock_redis_store, mock_dxlink
):
    """Test that valid ReconnectReason values trigger simulate_failure()."""
    # Setup pubsub mock with messages
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()

    # Mock message stream
    messages = [
        {"type": "subscribe", "channel": "subscription:simulate_failure"},
        {"type": "message", "data": b"auth_expired"},
        {"type": "message", "data": b"connection_dropped"},
        {"type": "message", "data": b"timeout"},
    ]

    async def mock_listen():
        for msg in messages:
            yield msg
            await asyncio.sleep(0.01)

    pubsub.listen = mock_listen
    mock_redis_store.redis.pubsub.return_value = pubsub

    # Start listener
    listener_task = asyncio.create_task(
        failure_trigger_listener(mock_redis_store, mock_dxlink)
    )
    await asyncio.sleep(0.2)  # Allow messages to be processed
    listener_task.cancel()

    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    # Verify simulate_failure called for each valid reason
    assert mock_dxlink.simulate_failure.call_count == 3
    mock_dxlink.simulate_failure.assert_any_call(ReconnectReason.AUTH_EXPIRED)
    mock_dxlink.simulate_failure.assert_any_call(ReconnectReason.CONNECTION_DROPPED)
    mock_dxlink.simulate_failure.assert_any_call(ReconnectReason.TIMEOUT)


@pytest.mark.asyncio
async def test_invalid_reason_logs_warning_no_crash(mock_redis_store, mock_dxlink):
    """Test that invalid values are logged as warnings without crashing."""
    # Setup pubsub mock with invalid message
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()

    messages = [
        {"type": "subscribe", "channel": "subscription:simulate_failure"},
        {"type": "message", "data": b"invalid_reason"},
        {"type": "message", "data": b"random_string"},
        {"type": "message", "data": b"12345"},
    ]

    async def mock_listen():
        for msg in messages:
            yield msg
            await asyncio.sleep(0.01)

    pubsub.listen = mock_listen
    mock_redis_store.redis.pubsub.return_value = pubsub

    # Start listener with logging capture
    with patch("tastytrade.subscription.orchestrator.logger") as mock_logger:
        listener_task = asyncio.create_task(
            failure_trigger_listener(mock_redis_store, mock_dxlink)
        )
        await asyncio.sleep(0.2)
        listener_task.cancel()

        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify warnings logged for invalid values
        assert mock_logger.warning.call_count >= 3
        mock_logger.warning.assert_any_call(
            "Invalid ReconnectReason received: %s", "invalid_reason"
        )

        # Verify simulate_failure NOT called for invalid values
        mock_dxlink.simulate_failure.assert_not_called()


@pytest.mark.asyncio
async def test_listener_cleanup_on_cancellation(mock_redis_store, mock_dxlink):
    """Test graceful shutdown with proper cleanup."""
    # Setup pubsub mock
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()

    async def mock_listen():
        # Keep yielding to simulate running listener
        while True:
            await asyncio.sleep(0.1)
            yield {"type": "keepalive"}

    pubsub.listen = mock_listen
    mock_redis_store.redis.pubsub.return_value = pubsub

    # Start and cancel listener
    listener_task = asyncio.create_task(
        failure_trigger_listener(mock_redis_store, mock_dxlink)
    )
    await asyncio.sleep(0.1)
    listener_task.cancel()

    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    # Verify cleanup called
    pubsub.unsubscribe.assert_called_once_with("subscription:simulate_failure")
    pubsub.close.assert_called_once()


@pytest.mark.asyncio
async def test_listener_handles_string_data(mock_redis_store, mock_dxlink):
    """Test that listener handles both bytes and string data."""
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()

    # Mix of bytes and string data
    messages = [
        {"type": "message", "data": b"auth_expired"},  # bytes
        {"type": "message", "data": "connection_dropped"},  # string
    ]

    async def mock_listen():
        for msg in messages:
            yield msg
            await asyncio.sleep(0.01)

    pubsub.listen = mock_listen
    mock_redis_store.redis.pubsub.return_value = pubsub

    listener_task = asyncio.create_task(
        failure_trigger_listener(mock_redis_store, mock_dxlink)
    )
    await asyncio.sleep(0.1)
    listener_task.cancel()

    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    # Both should trigger simulate_failure
    assert mock_dxlink.simulate_failure.call_count == 2


@pytest.mark.asyncio
async def test_listener_ignores_non_message_types(mock_redis_store, mock_dxlink):
    """Test that listener only processes 'message' type events."""
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()

    messages = [
        {"type": "subscribe", "channel": "subscription:simulate_failure"},
        {"type": "psubscribe", "channel": "something"},
        {"type": "message", "data": b"auth_expired"},  # Only this should process
        {"type": "pmessage", "data": b"timeout"},
    ]

    async def mock_listen():
        for msg in messages:
            yield msg
            await asyncio.sleep(0.01)

    pubsub.listen = mock_listen
    mock_redis_store.redis.pubsub.return_value = pubsub

    listener_task = asyncio.create_task(
        failure_trigger_listener(mock_redis_store, mock_dxlink)
    )
    await asyncio.sleep(0.1)
    listener_task.cancel()

    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    # Only the 'message' type should trigger simulate_failure
    mock_dxlink.simulate_failure.assert_called_once_with(ReconnectReason.AUTH_EXPIRED)
