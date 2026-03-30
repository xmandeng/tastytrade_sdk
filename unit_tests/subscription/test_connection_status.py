"""Tests for Redis connection health status updates."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.subscription.orchestrator import update_redis_connection_status


@pytest.fixture()
def mock_store() -> MagicMock:
    store = MagicMock()
    store.redis = AsyncMock()
    store.redis.hset = AsyncMock()
    store.redis.hdel = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_connected_status_sets_state_and_timestamp(mock_store: MagicMock) -> None:
    """Setting connected status writes state and timestamp."""
    await update_redis_connection_status(mock_store, state="connected")

    mock_store.redis.hset.assert_called_once()
    call_kwargs = mock_store.redis.hset.call_args
    mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1]["mapping"]
    assert mapping["state"] == "connected"
    assert "timestamp" in mapping
    assert "error" not in mapping


@pytest.mark.asyncio
async def test_connected_status_clears_error_field(mock_store: MagicMock) -> None:
    """Setting connected status removes the stale error field from Redis."""
    await update_redis_connection_status(mock_store, state="connected")

    mock_store.redis.hdel.assert_called_once_with("tastytrade:connection", "error")


@pytest.mark.asyncio
async def test_error_status_sets_error_field(mock_store: MagicMock) -> None:
    """Setting error status includes the error reason."""
    await update_redis_connection_status(
        mock_store, state="error", reason="connection_dropped"
    )

    call_kwargs = mock_store.redis.hset.call_args
    mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1]["mapping"]
    assert mapping["state"] == "error"
    assert mapping["error"] == "connection_dropped"


@pytest.mark.asyncio
async def test_error_status_does_not_clear_error_field(mock_store: MagicMock) -> None:
    """Setting error status does not call hdel since reason is provided."""
    await update_redis_connection_status(
        mock_store, state="error", reason="auth_expired"
    )

    mock_store.redis.hdel.assert_not_called()
