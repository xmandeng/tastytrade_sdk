"""Tests for AsyncSessionHandler.close() server-side session termination."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.connections.requests import AsyncSessionHandler


@pytest.mark.asyncio
async def test_close_terminates_server_session_when_active() -> None:
    """close() should DELETE /sessions before closing the HTTP client."""
    handler = AsyncSessionHandler.__new__(AsyncSessionHandler)
    handler.base_url = "https://api.example.com"
    handler.is_active = True

    mock_resp = MagicMock()
    mock_resp.status = 204
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.delete = MagicMock(return_value=mock_resp)
    mock_session.close = AsyncMock()
    handler.session = mock_session

    await handler.close()

    mock_session.delete.assert_called_once_with("https://api.example.com/sessions")
    mock_session.close.assert_awaited_once()
    assert handler.is_active is False


@pytest.mark.asyncio
async def test_close_skips_delete_when_not_active() -> None:
    """close() should not call DELETE /sessions if session is not active."""
    handler = AsyncSessionHandler.__new__(AsyncSessionHandler)
    handler.base_url = "https://api.example.com"
    handler.is_active = False

    mock_session = MagicMock()
    mock_session.delete = MagicMock()
    mock_session.close = AsyncMock()
    handler.session = mock_session

    await handler.close()

    mock_session.delete.assert_not_called()
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_handles_delete_failure_gracefully() -> None:
    """close() should still close HTTP client even if DELETE fails."""
    handler = AsyncSessionHandler.__new__(AsyncSessionHandler)
    handler.base_url = "https://api.example.com"
    handler.is_active = True

    mock_session = MagicMock()
    mock_session.delete = MagicMock(side_effect=ConnectionError("network down"))
    mock_session.close = AsyncMock()
    handler.session = mock_session

    await handler.close()

    mock_session.close.assert_awaited_once()
    assert handler.is_active is False
