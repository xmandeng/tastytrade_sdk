from typing import Any, Optional

import aiohttp

from tastytrade import Credentials
from tastytrade.exceptions import validate_async_response
from tastytrade.utilties import logger

QueryParams = Optional[dict[str, Any]]


class AsyncSessionHandler:
    """Tastytrade session handler for API interactions."""

    def __init__(self, credentials: Credentials) -> None:
        self.base_url: str = credentials.base_url
        self.login: str = credentials.login
        self.password: str = credentials.password
        self.remember_me: bool = credentials.remember_me
        self.session: aiohttp.ClientSession = aiohttp.ClientSession(
            headers={
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.is_active: bool = False

    async def create_session(self) -> None:
        """Create and authenticate a session with Tastytrade API."""
        if self.is_active:
            logger.warning("Session already active")
            return

        async with self.session.post(
            url=f"{self.base_url}/sessions",
            json={"login": self.login, "password": self.password, "remember-me": self.remember_me},
        ) as response:
            respense_data = await response.json()

            await validate_async_response(response)

            self.session.headers.update({"Authorization": respense_data["data"]["session-token"]})
            self.is_active = True

            logger.info("Session created successfully")

    async def get_dxlink_token(self) -> None:
        """Get the dxlink token."""
        async with self.session.get(url=f"{self.base_url}/api-quote-tokens") as response:
            await validate_async_response(response)

    async def close(self) -> None:
        """Close the session and cleanup resources."""
        if self.session:
            await self.session.close()
            self.is_active = False
            logger.info("Session closed successfully")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active
