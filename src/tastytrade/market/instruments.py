import asyncio
import logging
from typing import TypeVar, Union
from urllib.parse import quote

import polars as pl
from pydantic import BaseModel
from requests import Response

from tastytrade.connections.requests import AsyncSessionHandler, SessionHandler
from tastytrade.market.models import (
    CryptocurrencyInstrument,
    EquityInstrument,
    EquityOptionInstrument,
    FutureInstrument,
    FutureOptionInstrument,
)
from tastytrade.utils.validators import validate_async_response

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

INSTRUMENT_BATCH_SIZE = 50


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


class InstrumentsClient:
    """Async client for TastyTrade instrument endpoints."""

    def __init__(self, session: AsyncSessionHandler) -> None:
        self.session = session

    async def get_equity_options(
        self, symbols: list[str]
    ) -> list[EquityOptionInstrument]:
        """GET /instruments/equity-options/{symbol} for each symbol."""
        return await self.fetch_individual(
            "/instruments/equity-options", symbols, EquityOptionInstrument
        )

    async def get_future_options(
        self, symbols: list[str]
    ) -> list[FutureOptionInstrument]:
        """GET /instruments/future-options/{symbol} for each symbol."""
        return await self.fetch_individual(
            "/instruments/future-options", symbols, FutureOptionInstrument
        )

    async def get_equities(self, symbols: list[str]) -> list[EquityInstrument]:
        """GET /instruments/equities/{symbol} for each symbol."""
        return await self.fetch_individual(
            "/instruments/equities", symbols, EquityInstrument
        )

    async def get_futures(self, symbols: list[str]) -> list[FutureInstrument]:
        """GET /instruments/futures?symbol[]={sym1}&symbol[]={sym2}..."""
        return await self.fetch_batch("/instruments/futures", symbols, FutureInstrument)

    async def get_cryptocurrencies(
        self, symbols: list[str]
    ) -> list[CryptocurrencyInstrument]:
        """GET /instruments/cryptocurrencies?symbol[]={sym1}&symbol[]={sym2}..."""
        return await self.fetch_batch(
            "/instruments/cryptocurrencies", symbols, CryptocurrencyInstrument
        )

    async def fetch_individual(
        self, endpoint: str, symbols: list[str], model_cls: type[T]
    ) -> list[T]:
        """Fetch instruments one at a time via GET /endpoint/{symbol}."""
        if not symbols:
            return []

        async def fetch_one(symbol: str) -> T | None:
            encoded = quote(symbol, safe="")
            url = f"{self.session.base_url}{endpoint}/{encoded}"
            async with self.session.session.get(url) as response:
                if response.status == 404:
                    logger.debug("Instrument not found: %s%s", endpoint, symbol)
                    return None
                await validate_async_response(response)
                data = await response.json()
                item = data.get("data", {})
                try:
                    return model_cls.model_validate(item)
                except Exception as e:
                    logger.warning("Failed to parse %s instrument: %s", endpoint, e)
                    return None

        fetched = await asyncio.gather(*[fetch_one(s) for s in symbols])
        results = [r for r in fetched if r is not None]
        logger.info("Fetched %d instruments from %s", len(results), endpoint)
        return results

    async def fetch_batch(
        self, endpoint: str, symbols: list[str], model_cls: type[T]
    ) -> list[T]:
        """Batch-fetch instruments, ~50 symbols per request."""
        results: list[T] = []
        for i in range(0, len(symbols), INSTRUMENT_BATCH_SIZE):
            batch = symbols[i : i + INSTRUMENT_BATCH_SIZE]
            params = [("symbol[]", sym) for sym in batch]
            url = f"{self.session.base_url}{endpoint}"
            async with self.session.session.get(url, params=params) as response:
                await validate_async_response(response)
                data = await response.json()
                items = data.get("data", {}).get("items", [])
                for item in items:
                    try:
                        results.append(model_cls.model_validate(item))
                    except Exception as e:
                        logger.warning("Failed to parse %s instrument: %s", endpoint, e)
        logger.info("Fetched %d instruments from %s", len(results), endpoint)
        return results
