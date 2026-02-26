import os

import redis  # type: ignore

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor


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
        self.redis = redis.Redis(host=host, port=port)

    def process_event(self, event: BaseEvent) -> None:
        """Process an event: publish to pub/sub AND store latest in HSET."""
        event_json = event.model_dump_json()
        event_type = event.__class__.__name__
        symbol = event.eventSymbol

        # Pub/sub for real-time streaming (existing behavior)
        channel = f"market:{event_type}:{symbol}"
        self.redis.publish(channel=channel, message=event_json)

        # HSET for latest-value reads (new behavior)
        hset_key = f"tastytrade:latest:{event_type}"
        self.redis.hset(hset_key, symbol, event_json)


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
