"""Verify RedisPublisher satisfies the EventPublisher protocol."""

from tastytrade.messaging.publisher import EventPublisher
from tastytrade.providers.subscriptions import RedisPublisher


def test_redis_publisher_satisfies_event_publisher_protocol() -> None:
    assert issubclass(RedisPublisher, EventPublisher)
