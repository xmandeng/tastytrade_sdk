import json
from types import SimpleNamespace

import requests

from tastytrade import Credentials
from tastytrade.utilties import logger, response_to_class


class Session:
    """Tastytrade session."""

    session_info: SimpleNamespace
    api_quote_info: SimpleNamespace

    headers: dict[str, str | None] = {
        "Authorization": None,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials

    def create_session(self, remember_me: bool = True) -> None:
        """Login to the Tastytrade API."""
        payload = json.dumps(
            {
                "login": self.credentials.login,
                "password": self.credentials.password,
                "remember-me": remember_me,
            }
        )

        response = requests.request(
            "POST", self.credentials.base_url + "/sessions", headers=self.headers, data=payload
        )

        if response.status_code != 201:
            logger.error(f"Failed to login [{response.status_code}]")
            raise Exception(f"Failed to login [{response.status_code}]")

        self.session_info = response_to_class(json.loads(response.text)["data"])

        cookies = [f"{cookie.name}={cookie.value}" for cookie in response.cookies]
        self.session_info.cookies = ";".join(cookies)

        self.headers["Authorization"] = self.session_info.session_token

    def get_api_quote_token(self) -> None:
        """Get the quote token."""
        if "session_token" not in vars(self.session_info):
            logger.error("Session token not found. Please login first.")
            raise Exception("Session token not found. Please login first.")

        token_response = requests.get(
            self.credentials.base_url + "/api-quote-tokens", headers=self.headers
        )

        if token_response.status_code == 200:
            self.api_quote_info = response_to_class(token_response.json()["data"])
        else:
            logger.error(f"Failed to get quote token [{token_response.status_code}]")
            raise Exception(f"Failed to get quote token [{token_response.status_code}]")


def request_options_chains(session: Session, symbol: str) -> requests.Response:
    """Get the options chains for a given symbol."""

    if "session_token" not in vars(session.session_info):
        logger.error("Session token not found. Please login first.")
        raise Exception("Session token not found. Please login first.")

    payload: dict = {}

    response = requests.request(
        "GET",
        session.credentials.base_url + "/option-chains/" + symbol,
        headers=session.headers,
        data=payload,
    )

    if response.status_code != 200:
        logger.error(f"Failed to get options chains [{response.status_code}]")
        raise Exception(f"Failed to get options chains [{response.status_code}]")

    return response
