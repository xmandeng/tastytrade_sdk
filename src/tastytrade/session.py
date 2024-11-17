import json
import logging
from typing import Any, Optional

import requests
from injector import inject, singleton
from requests import Session

from tastytrade import Credentials
from tastytrade.exceptions import validate_response

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)


@singleton
class SessionHandler:
    """Tastytrade session."""

    session = Session()
    is_active: bool = False

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

        self.create_session(**credentials.as_dict)

    def request(
        self, method: str, url: str, params: QueryParams = None, **kwargs
    ) -> requests.Response:
        # TODO Add URL params
        response = self.session.request(
            method, url, headers=self.session.headers, params=params, **kwargs
        )

        validate_response(response)

        return response

    def create_session(self, **kwargs) -> None:
        """Login to the Tastytrade API."""
        if self.is_session_active():
            logger.warning("Session already active")
            return

        response = self.request(
            method="POST",
            url=self.base_url + "/sessions",
            data=json.dumps(
                {
                    "login": kwargs.get("login"),
                    "password": kwargs.get("password"),
                    "remember-me": kwargs.get("remember_me"),
                }
            ),
        )

        self.session.headers.update({"Authorization": response.json()["data"]["session-token"]})

        logger.info("Session created successfully")
        self.is_active = True

    def close_session(self) -> None:
        """Close the Tastytrade session."""
        response = self.session.request("DELETE", self.base_url + "/sessions")

        if validate_response(response):
            logger.info("Session closed successfully")
            self.is_active = False
        else:
            logger.error(f"Failed to close session [{response.status_code}]")
            raise Exception(f"Failed to close session [{response.status_code}]")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active

    def get_api_quote_token(self) -> None:
        """Get the quote token."""
        response = self.session.request(
            method="GET",
            url=self.base_url + "/api-quote-tokens",
        )

        self.session.headers.update({"dxlink-url": response.json()["data"]["dxlink-url"]})
        self.session.headers.update({"token": response.json()["data"]["token"]})
