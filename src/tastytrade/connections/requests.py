import logging
from typing import Any, Optional

import aiohttp
import requests
from injector import inject
from requests import Session

from tastytrade.connections import Credentials
from tastytrade.connections.auth import (
    AuthStrategy,
    SyncAuthStrategy,
    create_auth_strategy,
    create_sync_auth_strategy,
)
from tastytrade.utils.validators import validate_async_response, validate_response

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)


class SessionHandler:
    """Tastytrade sync session handler with pluggable auth strategy."""

    session = Session()
    is_active: bool = False

    @classmethod
    @inject
    def create(cls, credentials: Credentials) -> "SessionHandler":
        strategy = create_sync_auth_strategy(credentials)
        instance = cls(credentials, strategy)
        instance.create_session()
        instance.get_dxlink_token()
        return instance

    @inject
    def __init__(
        self, credentials: Credentials, auth_strategy: SyncAuthStrategy
    ) -> None:
        self.base_url = credentials.base_url
        self.auth_strategy = auth_strategy

        self.session.headers.update(
            {
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def request(
        self, method: str, url: str, params: QueryParams = None, **kwargs: Any
    ) -> requests.Response:
        response = self.session.request(
            method, url, headers=self.session.headers, params=params, **kwargs
        )

        validate_response(response)

        return response

    def create_session(self) -> None:
        """Authenticate using the configured auth strategy."""
        if self.is_session_active():
            logger.warning("Session already active")
            return

        self.auth_strategy.authenticate(self.session, self.base_url)
        self.is_active = True

    def refresh_token_if_needed(self) -> None:
        """Delegate token refresh to the auth strategy."""
        self.auth_strategy.refresh_if_needed(self.session, self.base_url)

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
    """Tastytrade async session handler with pluggable auth strategy."""

    @classmethod
    async def create(cls, credentials: Credentials) -> "AsyncSessionHandler":
        strategy = create_auth_strategy(credentials)
        instance = cls(credentials, strategy)
        await instance.create_session()
        await instance.get_dxlink_token()
        return instance

    def __init__(self, credentials: Credentials, auth_strategy: AuthStrategy) -> None:
        self.base_url: str = credentials.base_url
        self.auth_strategy: AuthStrategy = auth_strategy
        self.session: aiohttp.ClientSession = aiohttp.ClientSession(
            headers={
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.is_active: bool = False

    async def create_session(self) -> None:
        """Authenticate using the configured auth strategy."""
        if self.is_active:
            logger.warning("Session already active")
            return

        await self.auth_strategy.authenticate(self.session, self.base_url)
        self.is_active = True

    async def refresh_token_if_needed(self) -> None:
        """Delegate token refresh to the auth strategy."""
        await self.auth_strategy.refresh_if_needed(self.session, self.base_url)

    async def get_dxlink_token(self) -> None:
        """Get the dxlink token."""
        await self.refresh_token_if_needed()

        async with self.session.get(
            url=f"{self.base_url}/api-quote-tokens"
        ) as response:
            response_data = await response.json()

            if await validate_async_response(response):
                logger.debug("Retrieved dxlink token")

            self.session.headers.update(
                {"dxlink-url": response_data["data"]["dxlink-url"]}
            )
            self.session.headers.update({"token": response_data["data"]["token"]})

    async def close(self) -> None:
        """Close the session and cleanup resources."""
        if self.session:
            if self.is_active:
                try:
                    async with self.session.delete(f"{self.base_url}/sessions") as resp:
                        if resp.status in range(200, 300):
                            logger.info("Server-side session terminated")
                        else:
                            logger.warning(
                                "Failed to terminate session: HTTP %s",
                                resp.status,
                            )
                except Exception as e:
                    logger.warning("Error terminating server-side session: %s", e)
            await self.session.close()
            self.is_active = False
            logger.info("Session closed")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active
