import logging
from typing import Union

import polars as pl
from requests import Response

from tastytrade.connections.requests import AsyncSessionHandler, SessionHandler

logger = logging.getLogger(__name__)


async def get_option_chains(
    session: Union[SessionHandler, AsyncSessionHandler],
    symbol: str,
) -> pl.DataFrame:
    """Get the options chains for a given symbol.

    Args:
        session: An active TastyTrade session
        symbol: The underlying symbol to get option chains for (e.g. "SPY")

    Returns
        The option chain data as returned by the TastyTrade API

    Raises
        Various TastytradeSdkError exceptions on API errors
    """
    # Handle async session
    if isinstance(session, AsyncSessionHandler):
        async with session.session.get(
            f"{session.base_url}/option-chains/{symbol}"
        ) as async_response:
            data = await async_response.json()

    # Handle sync session
    else:
        sync_response: Response = session.request(
            "GET",
            f"{session.base_url}/option-chains/{symbol}",
        )
        data = sync_response.json()

    return pl.DataFrame(data["data"]["items"])
