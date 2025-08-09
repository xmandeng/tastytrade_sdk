from __future__ import annotations

import asyncio
import logging
from typing import Dict

from redis import asyncio as aioredis  # type: ignore

from tastytrade.messaging.models.events import CandleEvent

from .schemas import DeltaMessage
from .state import SymbolIndicatorState, build_snapshot

logger = logging.getLogger(__name__)

RAW_PATTERN = "market:CandleEvent:*"
DELTA_CHANNEL_FMT = "analytics:delta:{symbol}"
SNAPSHOT_KEY_FMT = "snapshot:{symbol}"


class IndicatorWorker:
    def __init__(self, redis_url: str = "redis://redis:6379/0"):
        self.redis = aioredis.from_url(redis_url, decode_responses=True)
        self.states: Dict[str, SymbolIndicatorState] = {}

    async def run(self):
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe(RAW_PATTERN)
        logger.info("IndicatorWorker subscribed to %s", RAW_PATTERN)
        async for message in pubsub.listen():
            if message.get("type") not in {"pmessage", "message"}:
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                event = CandleEvent.model_validate_json(data)
            except Exception as e:  # pragma: no cover
                logger.debug("Failed to parse CandleEvent: %s", e)
                continue
            symbol = event.eventSymbol
            state = self.states.get(symbol)
            if state is None:
                state = SymbolIndicatorState(symbol)
                self.states[symbol] = state
            result = state.ingest(event)
            if result is None:
                continue
            candle_payload, macd, hma = result
            delta = DeltaMessage(
                symbol=symbol,
                candle=candle_payload,
                macd=macd,
                hma=hma,
            )
            await self.redis.publish(
                DELTA_CHANNEL_FMT.format(symbol=symbol), delta.model_dump_json()
            )
            snapshot = build_snapshot(symbol, candle_payload, macd, hma)
            await self.redis.set(
                SNAPSHOT_KEY_FMT.format(symbol=symbol), snapshot.model_dump_json()
            )


def start():  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    worker = IndicatorWorker()
    asyncio.run(worker.run())
