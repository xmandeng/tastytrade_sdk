"""Redis pub/sub feed for the charting module.

Subscribes to candle events and horizontal line annotations,
yielding typed events via async iteration.
"""

import json
import logging
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from redis.asyncio.client import PubSub

from tastytrade.config.manager import ConfigurationManager

logger = logging.getLogger(__name__)


class ChartFeed:
    """Subscribes to Redis channels for live chart data.

    Channels:
        market:CandleEvent:{candle_symbol}   — live candle updates
        market:HorizontalLine:{symbol}       — level annotations as they lock in
    """

    def __init__(self, config: ConfigurationManager) -> None:
        redis_url = config.get("REDIS_URL", "redis://localhost:6379")
        self.redis = aioredis.from_url(redis_url, decode_responses=True)
        self.pubsub: PubSub | None = None

    async def listen(
        self, symbol: str, candle_symbol: str
    ) -> AsyncIterator[tuple[str, dict]]:
        """Subscribe and yield (event_type, data) tuples.

        event_type is either "candle" or "level".
        """
        candle_channel = f"market:CandleEvent:{candle_symbol}"
        level_channel = f"market:HorizontalLine:{symbol}"

        ps = self.redis.pubsub()
        self.pubsub = ps
        await ps.subscribe(candle_channel, level_channel)

        logger.info("Subscribed to Redis: %s, %s", candle_channel, level_channel)

        async for message in ps.listen():
            if message["type"] != "message":
                continue

            channel = message["channel"]
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON on channel %s", channel)
                continue

            if channel == candle_channel:
                yield ("candle", data)
            elif channel == level_channel:
                yield ("level", data)

    async def close(self) -> None:
        """Unsubscribe and close Redis connection."""
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe()
                await self.pubsub.close()
            except Exception:
                pass
        try:
            await self.redis.close()
        except Exception:
            pass
