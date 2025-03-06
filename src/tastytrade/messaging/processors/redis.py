import redis  # type: ignore

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor


class RedisEventProcessor(BaseEventProcessor):
    name = "redis_pubsub"

    def __init__(self, redis_host="redis", redis_port=6379):
        super().__init__()
        self.redis = redis.Redis(host=redis_host, port=redis_port)

    def process_event(self, event: BaseEvent) -> None:
        """Process an event and publish it to Redis."""
        channel = f"market:{event.__class__.__name__}:{event.eventSymbol}"
        self.redis.publish(channel=channel, message=event.model_dump_json())


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
