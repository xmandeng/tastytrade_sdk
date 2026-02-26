"""Publishes AccountStreamer events (positions, balances) to Redis.

Reads from AccountStreamer asyncio queues and writes to Redis HSET
for on-demand reads, plus pub/sub for real-time consumers.
Single responsibility: account events -> Redis.
"""

import logging
import os
from typing import Optional

import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.accounts.models import AccountBalance, Position

logger = logging.getLogger(__name__)


class AccountStreamPublisher:
    """Publishes account events to Redis HSET + pub/sub."""

    POSITIONS_KEY = "tastytrade:positions"
    BALANCES_KEY = "tastytrade:balances"

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        self.redis: aioredis.Redis = aioredis.Redis(host=host, port=port)  # type: ignore[type-arg]

    async def publish_position(self, position: Position) -> None:
        """Write position to Redis HSET. Remove if quantity is zero (closed)."""
        key = position.streamer_symbol or position.symbol
        if position.quantity == 0.0:
            await self.redis.hdel(self.POSITIONS_KEY, key)
            logger.info("Removed closed position: %s", key)
        else:
            await self.redis.hset(
                self.POSITIONS_KEY, key, position.model_dump_json(by_alias=True)
            )
            await self.redis.publish(
                channel="tastytrade:events:CurrentPosition",
                message=position.model_dump_json(by_alias=True),
            )
            logger.debug("Published position: %s qty=%s", key, position.quantity)

    async def publish_balance(self, balance: AccountBalance) -> None:
        """Write balance to Redis HSET."""
        await self.redis.hset(
            self.BALANCES_KEY,
            balance.account_number,
            balance.model_dump_json(by_alias=True),
        )
        logger.debug("Published balance: %s", balance.account_number)

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
