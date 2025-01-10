import requests

from tastytrade.sessions.requests import SessionHandler


def request_options_chains(session: SessionHandler, symbol: str) -> requests.Response:
    """Get the options chains for a given symbol."""
    response = session.request(
        "GET",
        session.base_url + "/option-chains/" + symbol,
    )

    return response
