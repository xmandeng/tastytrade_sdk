"""SPXW 0DTE chain resolution and batched market-data fetch.

Same REST pattern as the GEX backend client: option metadata via
``get_option_chain`` and pricing/Greeks via batched
``/market-data/by-type?equity-option=<csv>``.
"""

import logging
from typing import Any, Sequence

import polars as pl

from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.market.option_chains import get_option_chain

from research.tt156_zero_dte_butterfly.config import OPTION_ROOT, SYMBOL

logger = logging.getLogger(__name__)

MARKET_DATA_CHUNK = 90

FLOAT_FIELDS = {
    "bid": "bid",
    "ask": "ask",
    "mid": "mid",
    "mark": "mark",
    "last": "last",
    "delta": "delta",
    "gamma": "gamma",
    "theta": "theta",
    "vega": "vega",
    "volatility": "iv",
    "volume": "volume",
    "open-interest": "oi",
}


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def resolve_chain(
    session: AsyncSessionHandler,
    expiration: str,
    spot: float,
    window: float,
) -> pl.DataFrame:
    """Fetch the SPXW chain for ``expiration``, strikes within ``spot ± window``.

    Filters on the explicit expiration date rather than dte==0 — overnight,
    the API still reports the prior (already expired) session as dte 0.
    """
    df = await get_option_chain(session, SYMBOL)
    df = df.filter(
        (pl.col("root") == OPTION_ROOT)
        & (pl.col("expiration") == expiration)
        & (pl.col("strike") >= spot - window)
        & (pl.col("strike") <= spot + window)
    )
    logger.info(
        "Resolved %d options for %s exp=%s strikes %.0f-%.0f",
        df.height,
        OPTION_ROOT,
        expiration,
        spot - window,
        spot + window,
    )
    return df


async def fetch_market_data(
    session: AsyncSessionHandler, occ_symbols: Sequence[str]
) -> dict[str, dict[str, float | None]]:
    """Batched market data for OCC symbols → {occ_symbol: {field: value}}."""
    out: dict[str, dict[str, float | None]] = {}
    symbols = list(occ_symbols)
    for start in range(0, len(symbols), MARKET_DATA_CHUNK):
        chunk = symbols[start : start + MARKET_DATA_CHUNK]
        async with session.session.get(
            f"{session.base_url}/market-data/by-type",
            params={"equity-option": ",".join(chunk)},
        ) as resp:
            data = await resp.json()
        for item in data.get("data", {}).get("items", []):
            symbol = item.get("symbol")
            if not symbol:
                continue
            out[symbol] = {
                name: parse_float(item.get(api_field))
                for api_field, name in FLOAT_FIELDS.items()
            }
    return out


async def fetch_spot_rest(session: AsyncSessionHandler) -> float:
    """SPX spot via REST (fallback when the live candle stream is quiet)."""
    async with session.session.get(
        f"{session.base_url}/market-data/by-type",
        params={"index": SYMBOL},
    ) as resp:
        data = await resp.json()
    items = data.get("data", {}).get("items", [])
    if not items:
        raise ValueError("No spot data for SPX")
    item = items[0]
    spot = parse_float(item.get("mark")) or parse_float(item.get("last"))
    if spot is None:
        raise ValueError("No usable SPX spot field")
    return spot


async def fetch_index_summary(session: AsyncSessionHandler) -> dict[str, float | None]:
    """Prior close / open / day range for SPX from the index market-data item."""
    async with session.session.get(
        f"{session.base_url}/market-data/by-type",
        params={"index": SYMBOL},
    ) as resp:
        data = await resp.json()
    items = data.get("data", {}).get("items", [])
    item = items[0] if items else {}
    return {
        "prev_close": parse_float(item.get("prev-close")),
        "open": parse_float(item.get("open")),
        "day_high": parse_float(item.get("day-high-price")),
        "day_low": parse_float(item.get("day-low-price")),
        "last": parse_float(item.get("last")),
    }
