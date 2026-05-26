"""GEX snapshot orchestrator + Redis cache (runtime model A, TT-138 §6.3).

``take_snapshot`` is the request-handler/orchestrator entry point. It cache-checks
Redis ``gex:snapshot:<symbol>:<expiry>`` (TTL ~60s); on a fresh hit it returns the
cached envelope (zero REST), on a miss it runs the pipeline
(client → compute → levels), caches the result, and returns it. The caller
consumes the returned envelope directly — Redis is an internal side-cache, not
the delivery channel (the key model-A distinction).
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

import redis.asyncio as aioredis

from tastytrade.analytics.gex.client import (
    fetch_chain_for_expirations,
    fetch_option_market_data,
    fetch_spot,
    resolve_symbol_context,
)
from tastytrade.analytics.gex.compute import aggregate_by_strike, compute_option_gex
from tastytrade.analytics.gex.levels import identify_levels
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.config.manager import RedisConfigManager

logger = logging.getLogger(__name__)

SNAPSHOT_TTL_SECONDS = 60
SNAPSHOT_KEY_PREFIX = "gex:snapshot"


@dataclass(frozen=True)
class SnapshotEnvelope:
    """A complete point-in-time GEX snapshot, serialisable for transport/cache."""

    symbol: str
    spot: float
    multiplier: float
    expirations: list[str]
    computed_at: str  # ISO-8601 UTC
    strikes: list[dict]  # per-(expiration, strike) GEX rows
    levels: list[dict]  # serialised Levels, one per expiration

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "SnapshotEnvelope":
        return cls(**json.loads(raw))


def snapshot_key(symbol: str, expirations: Sequence[str]) -> str:
    """Redis cache key: ``gex:snapshot:<symbol>:<sorted,comma-joined expiries>``."""
    return f"{SNAPSHOT_KEY_PREFIX}:{symbol}:{','.join(sorted(expirations))}"


def redis_client() -> aioredis.Redis:
    """Async Redis client resolved from ``REDIS_HOST``/``REDIS_PORT`` (codebase convention)."""
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    return aioredis.Redis(host=host, port=port, decode_responses=True)


async def take_snapshot(
    symbol: str,
    expirations: Sequence[str],
    *,
    session: Optional[AsyncSessionHandler] = None,
    redis: Optional[aioredis.Redis] = None,
    use_cache: bool = True,
) -> SnapshotEnvelope:
    """Take a GEX snapshot for ``symbol`` at ``expirations`` (runtime model A).

    Args:
        symbol: Underlying symbol (e.g. ``"SPX"``).
        expirations: One or more expiration dates (``YYYY-MM-DD``).
        session: Optional pre-authenticated session (else one is created and closed).
        redis: Optional Redis client (else one is created from env).
        use_cache: When ``True``, serve a fresh cached envelope if present.

    Returns:
        The :class:`SnapshotEnvelope` (cached or freshly computed).

    Raises:
        ValueError: when no strikes match the symbol/expirations within the window.
    """
    key = snapshot_key(symbol, expirations)
    cache = redis or redis_client()

    if use_cache:
        cached = await cache.get(key)
        if cached:
            logger.info("GEX snapshot cache HIT %s", key)
            return SnapshotEnvelope.from_json(cached)

    owns_session = session is None
    if session is None:
        creds = Credentials(RedisConfigManager(), env="Live")
        session = await AsyncSessionHandler.create(creds)

    try:
        ctx = await resolve_symbol_context(session, symbol)
        spot = await fetch_spot(session, ctx)
        chain = await fetch_chain_for_expirations(session, symbol, expirations, spot)
        if chain.is_empty():
            raise ValueError(
                f"No strikes for {symbol} at {list(expirations)} within the ±10% window"
            )
        market_data = await fetch_option_market_data(session, chain["symbol"].to_list())
        merged = chain.join(market_data, on="symbol", how="inner")
        priced = compute_option_gex(merged, spot, ctx.multiplier)
        strikes = aggregate_by_strike(priced)
        levels = identify_levels(strikes, spot)

        envelope = SnapshotEnvelope(
            symbol=symbol,
            spot=spot,
            multiplier=ctx.multiplier,
            expirations=sorted(expirations),
            computed_at=datetime.now(timezone.utc).isoformat(),
            strikes=strikes.to_dicts(),
            levels=[asdict(level) for level in levels],
        )
    finally:
        if owns_session:
            await session.close()

    await cache.set(key, envelope.to_json(), ex=SNAPSHOT_TTL_SECONDS)
    logger.info(
        "GEX snapshot computed + cached %s (%d strikes, spot=%.2f)",
        key,
        len(envelope.strikes),
        envelope.spot,
    )
    return envelope
