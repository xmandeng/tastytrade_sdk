"""Unified option chain fetcher for equities and futures.

Single entry point to retrieve option chains from the TastyTrade API,
auto-detecting equity vs futures by symbol prefix. Returns a consistent
Polars DataFrame regardless of instrument type.

Endpoints used:
- Equities/Indices: GET /option-chains/{symbol}/nested
- Futures: GET /futures-option-chains/{product_code}
"""

import logging
from typing import Optional

import polars as pl

from tastytrade.connections.requests import AsyncSessionHandler

logger = logging.getLogger(__name__)


def is_futures_symbol(symbol: str) -> bool:
    """Detect futures symbols by leading slash (e.g., /GC, /ES, /CL)."""
    return symbol.startswith("/")


def futures_product_code(symbol: str) -> str:
    """Extract product code from a futures symbol (e.g., /GC → GC)."""
    return symbol.lstrip("/")


async def fetch_equity_chain(session: AsyncSessionHandler, symbol: str) -> pl.DataFrame:
    """Fetch option chain for an equity/index/ETF via the nested endpoint.

    GET /option-chains/{symbol}/nested returns a hierarchical response
    with multiple root symbols (e.g., SPX + SPXW for S&P 500 index).
    """
    async with session.session.get(
        f"{session.base_url}/option-chains/{symbol}/nested"
    ) as response:
        data = await response.json()

    items = data.get("data", {}).get("items", [])
    if not items:
        logger.warning("No option chain data returned for %s", symbol)
        return pl.DataFrame()

    rows: list[dict] = []
    for item in items:
        root = item.get("root-symbol", "")
        underlying = item.get("underlying-symbol", symbol)
        shares_per_contract = item.get("shares-per-contract", 100)

        for exp in item.get("expirations", []):
            exp_date = exp["expiration-date"]
            exp_type = exp.get("expiration-type", "Regular")
            settlement = exp.get("settlement-type")
            dte = exp.get("days-to-expiration")

            for strike in exp.get("strikes", []):
                base = {
                    "underlying": underlying,
                    "root": root,
                    "expiration": exp_date,
                    "expiration_type": exp_type,
                    "settlement": settlement,
                    "dte": dte,
                    "strike": float(strike["strike-price"]),
                    "shares_per_contract": shares_per_contract,
                }
                if strike.get("call"):
                    rows.append(
                        {
                            **base,
                            "option_type": "C",
                            "symbol": strike["call"],
                            "streamer_symbol": strike.get("call-streamer-symbol", ""),
                        }
                    )
                if strike.get("put"):
                    rows.append(
                        {
                            **base,
                            "option_type": "P",
                            "symbol": strike["put"],
                            "streamer_symbol": strike.get("put-streamer-symbol", ""),
                        }
                    )

    logger.info("Fetched %d options for %s (%d roots)", len(rows), symbol, len(items))
    return pl.DataFrame(rows)


async def fetch_futures_chain(
    session: AsyncSessionHandler, symbol: str
) -> pl.DataFrame:
    """Fetch option chain for a futures product via the flat endpoint.

    GET /futures-option-chains/{product_code} returns a flat list of
    individual option instruments across all contract months.
    """
    product_code = futures_product_code(symbol)
    async with session.session.get(
        f"{session.base_url}/futures-option-chains/{product_code}"
    ) as response:
        data = await response.json()

    items = data.get("data", {}).get("items", [])
    if not items:
        logger.warning("No futures option chain data returned for %s", symbol)
        return pl.DataFrame()

    rows: list[dict] = []
    for item in items:
        product = item.get("future-option-product", {})
        rows.append(
            {
                "underlying": item.get("underlying-symbol", ""),
                "root": item.get("root-symbol", ""),
                "expiration": item["expiration-date"],
                "expiration_type": product.get("expiration-type", "Regular"),
                "settlement": item.get("settlement-type"),
                "dte": item.get("days-to-expiration"),
                "strike": float(item["strike-price"]),
                "shares_per_contract": None,
                "option_type": item["option-type"][0],
                "symbol": item["symbol"],
                "streamer_symbol": item.get("streamer-symbol", ""),
                "option_root": item.get("option-root-symbol", ""),
                "product_code": item.get("product-code", ""),
                "exchange": item.get("exchange", ""),
            }
        )

    logger.info(
        "Fetched %d futures options for %s (%d underlyings)",
        len(rows),
        symbol,
        len({r["underlying"] for r in rows}),
    )
    return pl.DataFrame(rows)


def filter_by_dte(
    df: pl.DataFrame,
    target_dtes: list[int],
) -> pl.DataFrame:
    """Filter to the closest available expiration for each target DTE.

    For each target DTE, finds the expiration with the smallest absolute
    difference and includes all strikes for that expiration.

    Args:
        df: Full option chain DataFrame (must have 'dte' column).
        target_dtes: List of target days-to-expiration (e.g., [0, 30, 45]).

    Returns:
        Filtered DataFrame containing only strikes at matched expirations.
    """
    if df.is_empty() or not target_dtes:
        return df

    available_dtes = df["dte"].unique().sort().to_list()
    if not available_dtes:
        return df

    matched_dtes: set[int] = set()
    for target in target_dtes:
        closest = min(available_dtes, key=lambda d: abs(d - target))
        matched_dtes.add(closest)

    return df.filter(pl.col("dte").is_in(list(matched_dtes)))


async def get_option_chain(
    session: AsyncSessionHandler,
    symbol: str,
    target_dtes: Optional[list[int]] = None,
) -> pl.DataFrame:
    """Fetch an option chain for any symbol with optional DTE filtering.

    Auto-detects equity vs futures by symbol prefix:
    - Slash prefix (e.g., /GC, /ES) → futures option chain
    - No slash (e.g., SPX, CSCO, XLE) → equity/index option chain

    Args:
        session: Authenticated TastyTrade session.
        symbol: Underlying symbol (e.g., "SPX", "/GC", "CSCO").
        target_dtes: Optional list of target DTEs. Returns closest match
            for each. If None, returns the full chain.

    Returns:
        Polars DataFrame with columns:
            underlying, root, expiration, expiration_type, settlement,
            dte, strike, shares_per_contract, option_type, symbol,
            streamer_symbol
        Futures chains additionally include:
            option_root, product_code, exchange
    """
    if is_futures_symbol(symbol):
        df = await fetch_futures_chain(session, symbol)
    else:
        df = await fetch_equity_chain(session, symbol)

    if target_dtes:
        df = filter_by_dte(df, target_dtes)

    return df
