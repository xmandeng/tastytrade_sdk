"""Resolves position streamer symbols into DXLink subscriptions.

Event-driven: listens to Redis pub/sub for position changes, diffs against
currently subscribed symbols, and calls subscribe/unsubscribe on DXLink.
Single responsibility: position symbols -> DXLink subscriptions.
"""

import asyncio
import logging
import os
from typing import Optional, Protocol

import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.accounts.publisher import AccountStreamPublisher

logger = logging.getLogger(__name__)

POSITION_EVENTS_CHANNEL = "tastytrade:events:CurrentPosition"


class SymbolSubscriber(Protocol):
    """Protocol for anything that can subscribe/unsubscribe symbols."""

    async def subscribe(self, symbols: list[str]) -> None: ...
    async def unsubscribe(self, symbols: list[str]) -> None: ...


class PositionSymbolResolver:
    """Reacts to position changes and manages DXLink subscriptions."""

    def __init__(
        self,
        dxlink: SymbolSubscriber,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        self.redis: aioredis.Redis = aioredis.Redis(host=host, port=port)  # type: ignore[type-arg]
        self.dxlink = dxlink
        self.subscribed_symbols: set[str] = set()

    async def resolve(self) -> None:
        """Read positions from Redis, diff, subscribe/unsubscribe."""
        raw = await self.redis.hgetall(AccountStreamPublisher.POSITIONS_KEY)
        current_symbols = {key.decode("utf-8") for key in raw.keys()}

        to_subscribe = current_symbols - self.subscribed_symbols
        to_unsubscribe = self.subscribed_symbols - current_symbols

        if to_subscribe:
            await self.dxlink.subscribe(sorted(to_subscribe))
            logger.info("Subscribed %d position symbols", len(to_subscribe))

        if to_unsubscribe:
            await self.dxlink.unsubscribe(sorted(to_unsubscribe))
            logger.info("Unsubscribed %d closed symbols", len(to_unsubscribe))

        self.subscribed_symbols = current_symbols

    async def listen(self) -> None:
        """Subscribe to position events and resolve on each change.

        Performs an initial resolve to catch positions already in Redis,
        then listens to the pub/sub channel for real-time updates.
        Runs until cancelled.
        """
        await self.resolve()
        logger.info("Position resolver: initial sync complete, listening for changes")

        pubsub = self.redis.pubsub()
        await pubsub.subscribe(POSITION_EVENTS_CHANNEL)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        await self.resolve()
                    except Exception as e:
                        logger.error("Position resolver error: %s", e)
        except asyncio.CancelledError:
            logger.info("Position resolver stopped")
        finally:
            await pubsub.unsubscribe(POSITION_EVENTS_CHANNEL)
            await pubsub.close()
