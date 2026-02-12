"""Authentication strategies for TastyTrade API.

Provides a strategy pattern for environment-aware authentication:
- OAuth2AuthStrategy: For Live environment (POST /oauth/token with refresh_token grant)
- LegacyAuthStrategy: For Sandbox environment (POST /sessions with login/password)

Usage:
    strategy = create_auth_strategy(credentials)
    await strategy.authenticate(session, base_url)
    await strategy.refresh_if_needed(session, base_url)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tastytrade.connections import Credentials

import aiohttp
import requests as req

from tastytrade.utils.validators import validate_async_response, validate_response

logger = logging.getLogger(__name__)

# Refresh the token 60 seconds before it expires
TOKEN_REFRESH_BUFFER_SECONDS = 60


# ---------------------------------------------------------------------------
# Async Protocols and Strategies
# ---------------------------------------------------------------------------


class AuthStrategy(Protocol):
    """Protocol for async authentication strategies."""

    async def authenticate(
        self, session: aiohttp.ClientSession, base_url: str
    ) -> None: ...

    async def refresh_if_needed(
        self, session: aiohttp.ClientSession, base_url: str
    ) -> None: ...


class OAuth2AuthStrategy:
    """OAuth2 refresh_token grant authentication for Live environment.

    Exchanges a long-lived refresh token for short-lived access tokens (900s).
    Automatically refreshes when the token is near expiry.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.token_expires_at: float = 0.0

    async def authenticate(self, session: aiohttp.ClientSession, base_url: str) -> None:
        async with session.post(
            url=f"{base_url}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
        ) as response:
            validate_async_response(response)
            data = await response.json()

        access_token = data["access_token"]
        expires_in = data.get("expires_in", 900)

        session.headers.update({"Authorization": f"Bearer {access_token}"})
        self.token_expires_at = (
            time.monotonic() + expires_in - TOKEN_REFRESH_BUFFER_SECONDS
        )
        logger.info("Session created via OAuth2")

    async def refresh_if_needed(
        self, session: aiohttp.ClientSession, base_url: str
    ) -> None:
        if time.monotonic() >= self.token_expires_at:
            logger.info("Access token near expiry, refreshing")
            await self.authenticate(session, base_url)


class LegacyAuthStrategy:
    """Legacy session-token authentication for Sandbox environment.

    Uses POST /sessions with login/password to obtain a session token.
    Session tokens are long-lived and do not require refresh.
    """

    def __init__(self, login: str, password: str) -> None:
        self.login = login
        self.password = password

    async def authenticate(self, session: aiohttp.ClientSession, base_url: str) -> None:
        async with session.post(
            url=f"{base_url}/sessions",
            json={
                "login": self.login,
                "password": self.password,
                "remember-me": True,
            },
        ) as response:
            validate_async_response(response)
            data = await response.json()

        session_token = data["data"]["session-token"]
        session.headers.update({"Authorization": session_token})
        logger.info("Session created via legacy login")

    async def refresh_if_needed(
        self, session: aiohttp.ClientSession, base_url: str
    ) -> None:
        pass  # Legacy sessions are long-lived


# ---------------------------------------------------------------------------
# Sync Protocols and Strategies
# ---------------------------------------------------------------------------


class SyncAuthStrategy(Protocol):
    """Protocol for sync authentication strategies."""

    def authenticate(self, session: req.Session, base_url: str) -> None: ...

    def refresh_if_needed(self, session: req.Session, base_url: str) -> None: ...


class SyncOAuth2AuthStrategy:
    """Sync OAuth2 refresh_token grant authentication for Live environment."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.token_expires_at: float = 0.0

    def authenticate(self, session: req.Session, base_url: str) -> None:
        response = session.post(
            url=f"{base_url}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
        )
        validate_response(response)

        data = response.json()
        access_token = data["access_token"]
        expires_in = data.get("expires_in", 900)

        session.headers.update({"Authorization": f"Bearer {access_token}"})
        self.token_expires_at = (
            time.monotonic() + expires_in - TOKEN_REFRESH_BUFFER_SECONDS
        )
        logger.info("Session created via OAuth2")

    def refresh_if_needed(self, session: req.Session, base_url: str) -> None:
        if time.monotonic() >= self.token_expires_at:
            logger.info("Access token near expiry, refreshing")
            self.authenticate(session, base_url)


class SyncLegacyAuthStrategy:
    """Sync legacy session-token authentication for Sandbox environment."""

    def __init__(self, login: str, password: str) -> None:
        self.login = login
        self.password = password

    def authenticate(self, session: req.Session, base_url: str) -> None:
        response = session.post(
            url=f"{base_url}/sessions",
            json={
                "login": self.login,
                "password": self.password,
                "remember-me": True,
            },
        )
        validate_response(response)

        data = response.json()
        session_token = data["data"]["session-token"]
        session.headers.update({"Authorization": session_token})
        logger.info("Session created via legacy login")

    def refresh_if_needed(self, session: req.Session, base_url: str) -> None:
        pass  # Legacy sessions are long-lived


# ---------------------------------------------------------------------------
# Factory Functions
# ---------------------------------------------------------------------------


def create_auth_strategy(credentials: Credentials) -> AuthStrategy:
    """Select the appropriate async auth strategy based on environment.

    Args:
        credentials: Credentials instance with environment and auth fields.

    Returns:
        OAuth2AuthStrategy for Live, LegacyAuthStrategy for Sandbox.
    """
    if credentials.is_sandbox:
        if not credentials.login or not credentials.password:
            raise ValueError(
                "Sandbox environment requires TT_SANDBOX_USER and TT_SANDBOX_PASS"
            )
        return LegacyAuthStrategy(
            login=credentials.login,
            password=credentials.password,
        )

    if (
        not credentials.oauth_client_id
        or not credentials.oauth_client_secret
        or not credentials.oauth_refresh_token
    ):
        raise ValueError(
            "Live environment requires TT_OAUTH_CLIENT_ID, "
            "TT_OAUTH_CLIENT_SECRET, and TT_OAUTH_REFRESH_TOKEN"
        )
    return OAuth2AuthStrategy(
        client_id=credentials.oauth_client_id,
        client_secret=credentials.oauth_client_secret,
        refresh_token=credentials.oauth_refresh_token,
    )


def create_sync_auth_strategy(credentials: Credentials) -> SyncAuthStrategy:
    """Select the appropriate sync auth strategy based on environment.

    Args:
        credentials: Credentials instance with environment and auth fields.

    Returns:
        SyncOAuth2AuthStrategy for Live, SyncLegacyAuthStrategy for Sandbox.
    """
    if credentials.is_sandbox:
        if not credentials.login or not credentials.password:
            raise ValueError(
                "Sandbox environment requires TT_SANDBOX_USER and TT_SANDBOX_PASS"
            )
        return SyncLegacyAuthStrategy(
            login=credentials.login,
            password=credentials.password,
        )

    if (
        not credentials.oauth_client_id
        or not credentials.oauth_client_secret
        or not credentials.oauth_refresh_token
    ):
        raise ValueError(
            "Live environment requires TT_OAUTH_CLIENT_ID, "
            "TT_OAUTH_CLIENT_SECRET, and TT_OAUTH_REFRESH_TOKEN"
        )
    return SyncOAuth2AuthStrategy(
        client_id=credentials.oauth_client_id,
        client_secret=credentials.oauth_client_secret,
        refresh_token=credentials.oauth_refresh_token,
    )
