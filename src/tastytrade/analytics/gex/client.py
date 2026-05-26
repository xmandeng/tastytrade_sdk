"""REST data collection for GEX snapshots.

Four REST calls (TT-138 §2): option chain, spot, multiplier lookup, and
batched option market-data. v1 covers **equity-options only** (index options
like SPX query the ``equity-option`` market-data param too); futures-options
is post-v1 (§6.13).

The ±10%-of-spot strike pre-filter (§6.1) is applied here — flat, with no
DTE-conditional logic.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import polars as pl

from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.market.option_chains import get_option_chain

logger = logging.getLogger(__name__)

# Equity-options contract multiplier (OCC convention). Constant for the
# equity-options class; futures-options resolve a per-product value (post-v1).
EQUITY_OPTION_MULTIPLIER = 100.0

# ±10% of spot, flat — no DTE-conditional logic (TT-138 §6.1, locked 2026-05-25).
STRIKE_WINDOW_PCT = 0.10

# OCC symbols per /market-data/by-type request (URL-length safe chunk).
MARKET_DATA_CHUNK = 90


@dataclass(frozen=True)
class SymbolContext:
    """Per-symbol resolution: spot-key and contract multiplier.

    ``spot_key`` selects the ``/market-data/by-type`` query param
    (``index`` for indexes like SPX, ``equity`` for ETFs/equities). ``multiplier``
    is carried so the GEX formula site never branches on product class.
    """

    symbol: str
    spot_key: str
    multiplier: float


def parse_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; returns ``None`` for missing/invalid values."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def resolve_symbol_context(
    session: AsyncSessionHandler, symbol: str
) -> SymbolContext:
    """Resolve spot-key and multiplier for ``symbol`` (one REST call).

    Index-vs-equity is determined authoritatively via the equities instrument
    endpoint: a 200 means it is an equity/ETF, a non-200 means it is an index.
    Futures (leading ``/``) are out of v1 scope.

    Raises:
        NotImplementedError: for futures symbols (post-v1, TT-138 §6.13).
    """
    if symbol.startswith("/"):
        raise NotImplementedError(
            f"Futures-options is post-v1 (TT-138 §6.13); cannot snapshot {symbol!r}"
        )

    async with session.session.get(
        f"{session.base_url}/instruments/equities/{symbol}"
    ) as resp:
        spot_key = "equity" if resp.status == 200 else "index"

    logger.debug(
        "resolve_symbol_context(%s) -> spot_key=%s, M=%g",
        symbol,
        spot_key,
        EQUITY_OPTION_MULTIPLIER,
    )
    return SymbolContext(
        symbol=symbol, spot_key=spot_key, multiplier=EQUITY_OPTION_MULTIPLIER
    )


async def fetch_spot(session: AsyncSessionHandler, ctx: SymbolContext) -> float:
    """Fetch the underlying spot price via ``/market-data/by-type?<spot-key>=<symbol>``."""
    async with session.session.get(
        f"{session.base_url}/market-data/by-type",
        params={ctx.spot_key: ctx.symbol},
    ) as resp:
        data = await resp.json()

    items = data.get("data", {}).get("items", [])
    if not items:
        raise ValueError(f"No spot data for {ctx.symbol} (spot_key={ctx.spot_key})")

    item = items[0]
    mark = parse_float(item.get("mark") or item.get("last") or item.get("mid"))
    if mark is None:
        raise ValueError(f"No usable spot price field for {ctx.symbol}")
    return mark


async def fetch_chain_for_expirations(
    session: AsyncSessionHandler,
    symbol: str,
    expirations: Sequence[str],
    spot: float,
) -> pl.DataFrame:
    """Fetch the chain, filtered to ``expirations`` and ±10% of ``spot``.

    Reuses :func:`tastytrade.market.option_chains.get_option_chain`, then applies
    the expiration filter and the spot-relative strike window.
    """
    df = await get_option_chain(session, symbol)
    if df.is_empty():
        return df

    lo, hi = spot * (1 - STRIKE_WINDOW_PCT), spot * (1 + STRIKE_WINDOW_PCT)
    df = df.filter(
        pl.col("expiration").is_in(list(expirations))
        & (pl.col("strike") >= lo)
        & (pl.col("strike") <= hi)
    )
    logger.info(
        "Chain for %s: %d options across %d expirations within ±%.0f%% of spot (%.2f)",
        symbol,
        df.height,
        df["expiration"].n_unique() if df.height else 0,
        STRIKE_WINDOW_PCT * 100,
        spot,
    )
    return df


async def fetch_option_market_data(
    session: AsyncSessionHandler, occ_symbols: Sequence[str]
) -> pl.DataFrame:
    """Batched ``/market-data/by-type?equity-option=<csv>`` → gamma/OI/IV/mark per option.

    Chunks the OCC symbols to keep request URLs within length limits.

    Returns:
        DataFrame with columns ``symbol``, ``gamma``, ``open_interest``,
        ``volatility``, ``mark``. Empty when no symbols are supplied.
    """
    symbols = list(occ_symbols)
    if not symbols:
        return pl.DataFrame()

    rows: list[dict] = []
    for start in range(0, len(symbols), MARKET_DATA_CHUNK):
        chunk = symbols[start : start + MARKET_DATA_CHUNK]
        async with session.session.get(
            f"{session.base_url}/market-data/by-type",
            params={"equity-option": ",".join(chunk)},
        ) as resp:
            data = await resp.json()
        for item in data.get("data", {}).get("items", []):
            rows.append(
                {
                    "symbol": item.get("symbol"),
                    "gamma": parse_float(item.get("gamma")),
                    "open_interest": parse_float(item.get("open-interest")),
                    "volatility": parse_float(item.get("volatility")),
                    "mark": parse_float(item.get("mark")),
                }
            )

    logger.info("Fetched market data for %d/%d options", len(rows), len(symbols))
    return pl.DataFrame(rows) if rows else pl.DataFrame()
