"""Publishes AccountStreamer events (positions, balances, orders) to Redis.

Reads from AccountStreamer asyncio queues and writes to Redis HSET
for on-demand reads, plus pub/sub for real-time consumers.
Single responsibility: account events -> Redis.
"""

import json
import logging
import os
from typing import Optional, Union

import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.accounts.models import (
    AccountBalance,
    PlacedComplexOrder,
    PlacedOrder,
    Position,
    TradeChain,
)
from tastytrade.accounts.transactions import EntryCredit
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
    ORDER_CHANNEL = "tastytrade:events:Order"
    COMPLEX_ORDERS_KEY = "tastytrade:complex-orders"
    ENTRY_CREDITS_KEY = "tastytrade:entry_credits"
    ENTRY_CREDITS_CHANNEL = "tastytrade:events:EntryCreditsUpdated"
    TRADE_CHAINS_KEY = "tastytrade:trade_chains"
    TRADE_CHAIN_CHANNEL = "tastytrade:events:OrderChain"

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
            channel=self.ORDER_CHANNEL,
            message=order.model_dump_json(by_alias=True),
        )
        logger.info(
            "Published order %d status=%s symbol=%s legs=%d",
            order.id,
            order.status.value,
            order.underlying_symbol,
            len(order.legs),
        )

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
        logger.info(
            "Published complex order %d type=%s orders=%d",
            order.id,
            order.type.value,
            len(order.orders),
        )

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

    async def publish_entry_credits(self, credits: dict[str, EntryCredit]) -> None:
        """Write entry credits to Redis HSET and notify downstream consumers."""
        if not credits:
            return
        pipe = self.redis.pipeline()
        symbols = []
        for symbol, credit in credits.items():
            pipe.hset(self.ENTRY_CREDITS_KEY, symbol, credit.model_dump_json())
            symbols.append(symbol)
        await pipe.execute()

        await self.redis.publish(
            self.ENTRY_CREDITS_CHANNEL,
            json.dumps({"symbols": symbols, "count": len(symbols)}),
        )
        logger.info("Published entry credits for %d symbols", len(symbols))

    async def publish_trade_chain(self, chain: TradeChain) -> None:
        """Write trade chain to Redis HSET keyed by chain ID and notify via pub/sub."""
        await self.redis.hset(
            self.TRADE_CHAINS_KEY,
            chain.id,
            chain.model_dump_json(by_alias=True),
        )
        await self.redis.publish(
            channel=self.TRADE_CHAIN_CHANNEL,
            message=chain.model_dump_json(by_alias=True),
        )
        status = "open" if chain.computed_data.open else "closed"
        logger.info(
            "Published trade chain %s %s — %s (%s)",
            chain.id,
            chain.description,
            chain.underlying_symbol,
            status,
        )

    async def remove_entry_credit(self, symbol: str) -> None:
        """Remove an entry credit record for a closed position."""
        await self.redis.hdel(self.ENTRY_CREDITS_KEY, symbol)
        logger.info("Removed entry credit for closed position: %s", symbol)

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
