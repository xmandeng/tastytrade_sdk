"""Protocol definition for event publishing.

Uses typing.Protocol for structural subtyping — any class that implements
publish(event: BaseEvent) -> None is a valid EventPublisher without
explicit inheritance. RedisPublisher already satisfies this protocol.
"""

from typing import Protocol, runtime_checkable

from tastytrade.messaging.models.events import BaseEvent


@runtime_checkable
class EventPublisher(Protocol):
    """Structural protocol for event publishers.

    Concrete implementations:
    - RedisPublisher (providers/subscriptions.py) — publishes to Redis pub/sub
    """

    def publish(self, event: BaseEvent) -> None: ...
