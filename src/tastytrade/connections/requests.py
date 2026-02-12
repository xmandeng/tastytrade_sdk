import logging
import time
from typing import Any, Optional

import aiohttp
import requests
from injector import inject
from requests import Session

from tastytrade.connections import Credentials
from tastytrade.utils.validators import validate_async_response, validate_response

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)

# Refresh the token 60 seconds before it expires
TOKEN_REFRESH_BUFFER_SECONDS = 60


class SessionHandler:
    """Tastytrade session using OAuth2 authentication."""

    session = Session()
    is_active: bool = False

    @classmethod
    @inject
    def create(cls, credentials: Credentials) -> "SessionHandler":
        instance = cls(credentials)
        instance.create_session(credentials)
        instance.get_dxlink_token()
        return instance

    @inject
    def __init__(self, credentials: Credentials) -> None:
        self.base_url = credentials.base_url
        self.credentials = credentials
        self.token_expires_at: float = 0.0

        self.session.headers.update(
            {
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def request(
        self, method: str, url: str, params: QueryParams = None, **kwargs
    ) -> requests.Response:
        response = self.session.request(
            method, url, headers=self.session.headers, params=params, **kwargs
        )

        validate_response(response)

        return response

    def create_session(self, credentials: Credentials) -> None:
        """Authenticate with TastyTrade via OAuth2 refresh_token grant."""
        if self.is_session_active():
            logger.warning("Session already active")
            return

        self._obtain_access_token(credentials)
        logger.info("Session created via OAuth2")
        self.is_active = True

    def _obtain_access_token(self, credentials: Credentials) -> None:
        """Exchange refresh token for an access token."""
        response = self.session.post(
            url=f"{self.base_url}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": credentials.oauth_client_id,
                "client_secret": credentials.oauth_client_secret,
                "refresh_token": credentials.oauth_refresh_token,
            },
        )

        validate_response(response)

        data = response.json()
        access_token = data["access_token"]
        expires_in = data.get("expires_in", 900)

        self.session.headers.update({"Authorization": f"Bearer {access_token}"})
        self.token_expires_at = (
            time.monotonic() + expires_in - TOKEN_REFRESH_BUFFER_SECONDS
        )

    def refresh_token_if_needed(self) -> None:
        """Refresh the access token if it is near expiry."""
        if time.monotonic() >= self.token_expires_at:
            logger.info("Access token near expiry, refreshing")
            self._obtain_access_token(self.credentials)

    def close(self) -> None:
        """Close the session."""
        self.session.close()
        self.is_active = False
        logger.info("Session closed")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active

    def get_dxlink_token(self) -> None:
        """Get the quote token."""
        self.refresh_token_if_needed()

        response = self.session.request(
            method="GET",
            url=self.base_url + "/api-quote-tokens",
        )

        validate_response(response)

        self.session.headers.update(
            {"dxlink-url": response.json()["data"]["dxlink-url"]}
        )
        self.session.headers.update({"token": response.json()["data"]["token"]})


@inject
class AsyncSessionHandler:
    """Tastytrade async session handler using OAuth2 authentication."""

    @classmethod
    async def create(cls, credentials: Credentials) -> "AsyncSessionHandler":
        instance = cls(credentials)
        await instance.create_session(credentials)
        await instance.get_dxlink_token()
        return instance

    def __init__(self, credentials: Credentials) -> None:
        self.base_url: str = credentials.base_url
        self.credentials: Credentials = credentials
        self.token_expires_at: float = 0.0
        self.session: aiohttp.ClientSession = aiohttp.ClientSession(
            headers={
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.is_active: bool = False

    async def create_session(self, credentials: Credentials) -> None:
        """Authenticate with TastyTrade via OAuth2 refresh_token grant."""
        if self.is_active:
            logger.warning("Session already active")
            return

        await self._obtain_access_token(credentials)
        logger.info("Session created via OAuth2")
        self.is_active = True

    async def _obtain_access_token(self, credentials: Credentials) -> None:
        """Exchange refresh token for an access token."""
        async with self.session.post(
            url=f"{self.base_url}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": credentials.oauth_client_id,
                "client_secret": credentials.oauth_client_secret,
                "refresh_token": credentials.oauth_refresh_token,
            },
        ) as response:
            validate_async_response(response)
            data = await response.json()

        access_token = data["access_token"]
        expires_in = data.get("expires_in", 900)

        self.session.headers.update({"Authorization": f"Bearer {access_token}"})
        self.token_expires_at = (
            time.monotonic() + expires_in - TOKEN_REFRESH_BUFFER_SECONDS
        )

    async def refresh_token_if_needed(self) -> None:
        """Refresh the access token if it is near expiry."""
        if time.monotonic() >= self.token_expires_at:
            logger.info("Access token near expiry, refreshing")
            await self._obtain_access_token(self.credentials)

    async def get_dxlink_token(self) -> None:
        """Get the dxlink token."""
        await self.refresh_token_if_needed()

        async with self.session.get(
            url=f"{self.base_url}/api-quote-tokens"
        ) as response:
            response_data = await response.json()

            if validate_async_response(response):
                logger.debug("Retrieved dxlink token")

            self.session.headers.update(
                {"dxlink-url": response_data["data"]["dxlink-url"]}
            )
            self.session.headers.update({"token": response_data["data"]["token"]})

    async def close(self) -> None:
        """Close the session and cleanup resources."""
        if self.session:
            await self.session.close()
            self.is_active = False
            logger.info("Session closed")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active
