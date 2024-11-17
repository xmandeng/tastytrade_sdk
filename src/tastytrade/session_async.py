import logging
from typing import Any, Optional

import aiohttp
from injector import inject

from tastytrade import Credentials
from tastytrade.exceptions import validate_async_response

logger = logging.getLogger(__name__)

QueryParams = Optional[dict[str, Any]]


@inject
class AsyncSessionHandler:
    """Tastytrade session handler for API interactions."""

    @classmethod
    async def create_session(cls, credentials: Credentials) -> "AsyncSessionHandler":
        instance = cls(credentials)
        await instance.open(credentials)
        await instance.get_dxlink_token()
        return instance

    def __init__(self, credentials: Credentials) -> None:
        self.base_url: str = credentials.base_url
        self.session: aiohttp.ClientSession = aiohttp.ClientSession(
            headers={
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.is_active: bool = False

    async def open(self, credentials: Credentials) -> None:
        """Create and authenticate a session with Tastytrade API."""
        if self.is_active:
            logger.warning("Session already active")
            return

        async with self.session.post(
            url=f"{self.base_url}/sessions",
            json={
                "login": credentials.login,
                "password": credentials.password,
                "remember-me": credentials.remember_me,
            },
        ) as response:
            response_data = await response.json()
            validate_async_response(response)

            self.session.headers.update({"Authorization": response_data["data"]["session-token"]})

            logger.info("Session created successfully")
            self.is_active = True

    async def get_dxlink_token(self) -> None:
        """Get the dxlink token."""
        async with self.session.get(url=f"{self.base_url}/api-quote-tokens") as response:
            response_data = await response.json()

            validate_async_response(response)

            self.session.headers.update({"dxlink-url": response_data["data"]["dxlink-url"]})
            self.session.headers.update({"token": response_data["data"]["token"]})

            logger.debug("Retrieved dxlink token")

    async def close(self) -> None:
        """Close the session and cleanup resources."""
        if self.session:
            await self.session.close()
            self.is_active = False
            logger.info("Session closed")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active
