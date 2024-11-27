import json
import logging
from typing import Any, Optional

import aiohttp
import requests
from injector import inject
from requests import Session

from tastytrade.sessions import Credentials
from tastytrade.utils.validators import validate_async_response, validate_response

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)


class SessionHandler:
    """Tastytrade session."""

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
        # TODO Add URL params
        response = self.session.request(
            method, url, headers=self.session.headers, params=params, **kwargs
        )

        validate_response(response)

        return response

    def create_session(self, credentials: Credentials) -> None:
        """Login to the Tastytrade API."""
        if self.is_session_active():
            logger.warning("Session already active")
            return

        response = self.request(
            method="POST",
            url=self.base_url + "/sessions",
            data=json.dumps(
                {
                    "login": credentials.login,
                    "password": credentials.password,
                    "remember-me": credentials.remember_me,
                }
            ),
        )

        self.session.headers.update({"Authorization": response.json()["data"]["session-token"]})

        logger.info("Session created")
        self.is_active = True

    def close(self) -> None:
        """Close the Tastytrade session."""
        response = self.session.request("DELETE", self.base_url + "/sessions")

        if validate_response(response):
            logger.info("Session closed")
            self.is_active = False
        else:
            logger.error("Failed to close session [%s]", response.status_code)
            raise Exception("Failed to close session [%s]", response.status_code)

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active

    def get_dxlink_token(self) -> None:
        """Get the quote token."""
        response = self.session.request(
            method="GET",
            url=self.base_url + "/api-quote-tokens",
        )

        self.session.headers.update({"dxlink-url": response.json()["data"]["dxlink-url"]})
        self.session.headers.update({"token": response.json()["data"]["token"]})


@inject
class AsyncSessionHandler:
    """Tastytrade session handler for API interactions."""

    @classmethod
    async def create(cls, credentials: Credentials) -> "AsyncSessionHandler":
        instance = cls(credentials)
        await instance.create_session(credentials)
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

    async def create_session(self, credentials: Credentials) -> None:
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

            if validate_async_response(response):
                logger.info("Session created successfully")

            self.session.headers.update({"Authorization": response_data["data"]["session-token"]})
            self.is_active = True

    async def get_dxlink_token(self) -> None:
        """Get the dxlink token."""
        async with self.session.get(url=f"{self.base_url}/api-quote-tokens") as response:
            response_data = await response.json()

            if validate_async_response(response):
                logger.debug("Retrieved dxlink token")

            self.session.headers.update({"dxlink-url": response_data["data"]["dxlink-url"]})
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
