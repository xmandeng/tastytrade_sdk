import logging
import os
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor

logger = logging.getLogger(__name__)

# TT-157: the candle pipeline once lagged hours behind the tape with no
# signal anywhere. Warn when a published candle's bar time trails wall
# clock by more than the bar interval plus this margin. Rate-limited so a
# subscription backfill logs a heartbeat, not a flood.
CANDLE_LAG_WARN_SECONDS = float(os.environ.get("CANDLE_LAG_WARN_SECONDS", "120"))
CANDLE_LAG_WARN_EVERY_SECONDS = 60.0
INTERVAL_SECONDS = {
    "m": 60.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1800.0,
    "h": 3600.0,
    "1h": 3600.0,
    "d": 86400.0,
    "1d": 86400.0,
}


class RedisEventProcessor(BaseEventProcessor):
    name = "redis_pubsub"

    def __init__(self, redis_host: str | None = None, redis_port: int | None = None):
        super().__init__()
        host = (
            redis_host
            if redis_host is not None
            else os.environ.get("REDIS_HOST", "localhost")
        )
        port = (
            redis_port
            if redis_port is not None
            else int(os.environ.get("REDIS_PORT", "6379"))
        )
        self.redis: aioredis.Redis = aioredis.Redis(host=host, port=port)  # type: ignore[type-arg, arg-type]
        self.last_lag_warning = 0.0

    async def process_event(self, event: BaseEvent) -> None:  # type: ignore[override]
        """Process an event: publish to pub/sub AND store latest in HSET."""
        event_json = event.model_dump_json()
        event_type = event.__class__.__name__
        symbol = event.eventSymbol

        if event_type == "CandleEvent":
            self.warn_if_stale(event)

        # Pub/sub for real-time streaming
        channel = f"market:{event_type}:{symbol}"
        await self.redis.publish(channel=channel, message=event_json)

        # HSET for latest-value reads
        hset_key = f"tastytrade:latest:{event_type}"
        await self.redis.hset(hset_key, symbol, event_json)

    def warn_if_stale(self, event: BaseEvent) -> None:
        """Log (rate-limited) when a candle publishes far behind wall clock.

        A forming bar's time legitimately trails wall clock by up to its
        interval, so the threshold is interval + CANDLE_LAG_WARN_SECONDS.
        """
        bar_time = getattr(event, "time", None)
        if not isinstance(bar_time, datetime):
            return
        symbol = event.eventSymbol
        interval = symbol.split("{=")[-1].rstrip("}") if "{=" in symbol else ""
        interval_seconds = INTERVAL_SECONDS.get(interval)
        if interval_seconds is None:
            return
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        lag = (datetime.now(timezone.utc) - bar_time).total_seconds()
        if lag <= interval_seconds + CANDLE_LAG_WARN_SECONDS:
            return
        now = time.monotonic()
        if now - self.last_lag_warning < CANDLE_LAG_WARN_EVERY_SECONDS:
            return
        self.last_lag_warning = now
        logger.warning(
            "Candle publish lag: %s bar %s is %.0f s behind wall clock "
            "(pipeline backlog or backfill in progress)",
            symbol,
            bar_time.isoformat(),
            lag,
        )

    def close(self) -> None:
        """Schedule Redis connection close."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.redis.close())
        except RuntimeError:
            pass


"""
Helpful CLI commands:

# Monitor Redis for activity
redis-cli MONITOR

# Subscribe to a channel
redis-cli SUBSCRIBE "market:TradeEvent:*"

# Subscribe to a specific symbol
redis-cli SUBSCRIBE "market:TradeEvent:AAPL"

# Subscribe to all candle events
redis-cli PSUBSCRIBE "market:CandleEvent:*"

# Subscribe to all matching events
redis-cli PSUBSCRIBE "market:CandleEvent:SPX{*m}"

# List all keys in Redis
redis-cli keys "*"

# Delete all keys in Redis
redis-cli flushall

# Get the value of a key
redis-cli get <key>

# Set the value of a key
redis-cli set <key> <value>
"""
