"""Tests for authentication strategies (TT-47)."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.connections.auth import (
    LegacyAuthStrategy,
    OAuth2AuthStrategy,
    SyncLegacyAuthStrategy,
    SyncOAuth2AuthStrategy,
    create_auth_strategy,
    create_sync_auth_strategy,
)


# ---------------------------------------------------------------------------
# Factory function tests
# ---------------------------------------------------------------------------


def test_create_auth_strategy_returns_oauth2_for_live() -> None:
    creds = MagicMock()
    creds.is_sandbox = False
    creds.oauth_client_id = "client-id"
    creds.oauth_client_secret = "client-secret"
    creds.oauth_refresh_token = "refresh-token"

    strategy = create_auth_strategy(creds)
    assert isinstance(strategy, OAuth2AuthStrategy)


def test_create_auth_strategy_returns_legacy_for_sandbox() -> None:
    creds = MagicMock()
    creds.is_sandbox = True
    creds.login = "user"
    creds.password = "pass"

    strategy = create_auth_strategy(creds)
    assert isinstance(strategy, LegacyAuthStrategy)


def test_create_auth_strategy_raises_when_live_missing_oauth() -> None:
    creds = MagicMock()
    creds.is_sandbox = False
    creds.oauth_client_id = None
    creds.oauth_client_secret = "secret"
    creds.oauth_refresh_token = "token"

    with pytest.raises(ValueError, match="TT_OAUTH_CLIENT_ID"):
        create_auth_strategy(creds)


def test_create_auth_strategy_raises_when_sandbox_missing_login() -> None:
    creds = MagicMock()
    creds.is_sandbox = True
    creds.login = None
    creds.password = "pass"

    with pytest.raises(ValueError, match="TT_SANDBOX_USER"):
        create_auth_strategy(creds)


def test_create_sync_auth_strategy_returns_oauth2_for_live() -> None:
    creds = MagicMock()
    creds.is_sandbox = False
    creds.oauth_client_id = "client-id"
    creds.oauth_client_secret = "client-secret"
    creds.oauth_refresh_token = "refresh-token"

    strategy = create_sync_auth_strategy(creds)
    assert isinstance(strategy, SyncOAuth2AuthStrategy)


def test_create_sync_auth_strategy_returns_legacy_for_sandbox() -> None:
    creds = MagicMock()
    creds.is_sandbox = True
    creds.login = "user"
    creds.password = "pass"

    strategy = create_sync_auth_strategy(creds)
    assert isinstance(strategy, SyncLegacyAuthStrategy)


# ---------------------------------------------------------------------------
# OAuth2AuthStrategy tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth2_authenticate_sets_bearer_token() -> None:
    strategy = OAuth2AuthStrategy(
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )

    response_mock = AsyncMock()
    response_mock.status = 200
    response_mock.json = AsyncMock(
        return_value={"access_token": "test-access-token", "expires_in": 900}
    )
    response_mock.headers = {"content-type": "application/json"}

    context_manager = AsyncMock()
    context_manager.__aenter__ = AsyncMock(return_value=response_mock)
    context_manager.__aexit__ = AsyncMock(return_value=False)

    headers: dict[str, str] = {}
    session = MagicMock()
    session.post = MagicMock(return_value=context_manager)
    session.headers = MagicMock()
    session.headers.update = lambda d: headers.update(d)

    await strategy.authenticate(session, "https://api.tastyworks.com")

    assert headers["Authorization"] == "Bearer test-access-token"
    assert strategy.token_expires_at > 0


@pytest.mark.asyncio
async def test_oauth2_refresh_if_needed_refreshes_when_expired() -> None:
    strategy = OAuth2AuthStrategy(
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )
    # Set token as expired
    strategy.token_expires_at = time.monotonic() - 10

    response_mock = AsyncMock()
    response_mock.status = 200
    response_mock.json = AsyncMock(
        return_value={"access_token": "refreshed-token", "expires_in": 900}
    )
    response_mock.headers = {"content-type": "application/json"}

    context_manager = AsyncMock()
    context_manager.__aenter__ = AsyncMock(return_value=response_mock)
    context_manager.__aexit__ = AsyncMock(return_value=False)

    headers: dict[str, str] = {}
    session = MagicMock()
    session.post = MagicMock(return_value=context_manager)
    session.headers = MagicMock()
    session.headers.update = lambda d: headers.update(d)

    await strategy.refresh_if_needed(session, "https://api.tastyworks.com")

    assert headers["Authorization"] == "Bearer refreshed-token"


@pytest.mark.asyncio
async def test_oauth2_refresh_if_needed_skips_when_valid() -> None:
    strategy = OAuth2AuthStrategy(
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )
    # Set token as valid (expires far in the future)
    strategy.token_expires_at = time.monotonic() + 600

    session = MagicMock()
    session.post = MagicMock()

    await strategy.refresh_if_needed(session, "https://api.tastyworks.com")

    # post should NOT have been called
    session.post.assert_not_called()


# ---------------------------------------------------------------------------
# LegacyAuthStrategy tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_authenticate_sets_raw_session_token() -> None:
    strategy = LegacyAuthStrategy(login="user", password="pass")

    response_mock = AsyncMock()
    response_mock.status = 201
    response_mock.json = AsyncMock(
        return_value={"data": {"session-token": "raw-session-token-123"}}
    )
    response_mock.headers = {"content-type": "application/json"}

    context_manager = AsyncMock()
    context_manager.__aenter__ = AsyncMock(return_value=response_mock)
    context_manager.__aexit__ = AsyncMock(return_value=False)

    headers: dict[str, str] = {}
    session = MagicMock()
    session.post = MagicMock(return_value=context_manager)
    session.headers = MagicMock()
    session.headers.update = lambda d: headers.update(d)

    await strategy.authenticate(session, "https://api.cert.tastyworks.com")

    # Legacy sets raw token WITHOUT "Bearer " prefix
    assert headers["Authorization"] == "raw-session-token-123"


@pytest.mark.asyncio
async def test_legacy_refresh_if_needed_is_noop() -> None:
    strategy = LegacyAuthStrategy(login="user", password="pass")
    session = MagicMock()

    # Should not raise, should not call anything
    await strategy.refresh_if_needed(session, "https://api.cert.tastyworks.com")
    session.post.assert_not_called()


# ---------------------------------------------------------------------------
# Sync strategy tests
# ---------------------------------------------------------------------------


def test_sync_oauth2_authenticate_sets_bearer_token() -> None:
    strategy = SyncOAuth2AuthStrategy(
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )

    response_mock = MagicMock()
    response_mock.status_code = 200
    response_mock.json.return_value = {
        "access_token": "sync-access-token",
        "expires_in": 900,
    }

    headers: dict[str, str] = {}
    session = MagicMock()
    session.post.return_value = response_mock
    session.headers = MagicMock()
    session.headers.update = lambda d: headers.update(d)

    with patch("tastytrade.connections.auth.validate_response"):
        strategy.authenticate(session, "https://api.tastyworks.com")

    assert headers["Authorization"] == "Bearer sync-access-token"


def test_sync_legacy_authenticate_sets_raw_token() -> None:
    strategy = SyncLegacyAuthStrategy(login="user", password="pass")

    response_mock = MagicMock()
    response_mock.status_code = 201
    response_mock.json.return_value = {"data": {"session-token": "sync-raw-token"}}

    headers: dict[str, str] = {}
    session = MagicMock()
    session.post.return_value = response_mock
    session.headers = MagicMock()
    session.headers.update = lambda d: headers.update(d)

    with patch("tastytrade.connections.auth.validate_response"):
        strategy.authenticate(session, "https://api.cert.tastyworks.com")

    assert headers["Authorization"] == "sync-raw-token"
