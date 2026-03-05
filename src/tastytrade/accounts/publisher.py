"""Publishes AccountStreamer events (positions, balances, orders) to Redis.

Reads from AccountStreamer asyncio queues and writes to Redis HSET
for on-demand reads, plus pub/sub for real-time consumers.
Single responsibility: account events -> Redis.
"""

import logging
import os
from typing import Optional

import redis.asyncio as aioredis  # type: ignore[import-untyped]

from typing import Union

from tastytrade.accounts.models import (
    AccountBalance,
    PlacedComplexOrder,
    PlacedOrder,
    Position,
)
from tastytrade.market.models import (
    CryptocurrencyInstrument,
    EquityInstrument,
    EquityOptionInstrument,
    FutureInstrument,
    FutureOptionInstrument,
)

Instrument = Union[
    EquityOptionInstrument,
    FutureOptionInstrument,
    EquityInstrument,
    FutureInstrument,
    CryptocurrencyInstrument,
]

logger = logging.getLogger(__name__)


class AccountStreamPublisher:
    """Publishes account events to Redis HSET + pub/sub."""

    POSITIONS_KEY = "tastytrade:positions"
    BALANCES_KEY = "tastytrade:balances"
    INSTRUMENTS_KEY = "tastytrade:instruments"
    ORDERS_KEY = "tastytrade:orders"
    COMPLEX_ORDERS_KEY = "tastytrade:complex-orders"

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        self.redis: aioredis.Redis = aioredis.Redis(host=host, port=port)  # type: ignore[type-arg, arg-type]

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
        logger.debug("Published balance update")

    async def publish_order(self, order: PlacedOrder) -> None:
        """Write order to Redis HSET keyed by order ID."""
        await self.redis.hset(
            self.ORDERS_KEY,
            str(order.id),
            order.model_dump_json(by_alias=True),
        )
        await self.redis.publish(
            channel="tastytrade:events:Order",
            message=order.model_dump_json(by_alias=True),
        )
        logger.info("Published order %d status=%s", order.id, order.status.value)

    async def publish_complex_order(self, order: PlacedComplexOrder) -> None:
        """Write complex order to Redis HSET keyed by complex order ID."""
        await self.redis.hset(
            self.COMPLEX_ORDERS_KEY,
            str(order.id),
            order.model_dump_json(by_alias=True),
        )
        await self.redis.publish(
            channel="tastytrade:events:ComplexOrder",
            message=order.model_dump_json(by_alias=True),
        )
        logger.info("Published complex order %d type=%s", order.id, order.type.value)

    async def publish_instruments(self, instruments: list[Instrument]) -> None:
        """Write instrument details to Redis HSET. Key = symbol, value = JSON."""
        if not instruments:
            return
        pipe = self.redis.pipeline()
        for inst in instruments:
            pipe.hset(
                self.INSTRUMENTS_KEY, inst.symbol, inst.model_dump_json(by_alias=True)
            )
        await pipe.execute()
        logger.info("Published %d instruments to Redis", len(instruments))

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
