"""Generic engine runner — gives each engine a dedicated subscription.

Wires the subscription's on_update callback directly to the engine's
event handler. No queues, no polling — the Redis async listener fires
events directly into the engine.

Three-layer separation:
    cli.py    → What to run (factory: pick engine, channels, event type)
    runner.py → How to run (generic harness: wire subscription, manage lifecycle)
    engine    → The work (pure state machine: event in, signal out)
"""

import asyncio
import logging
from typing import Any, Callable

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.providers.subscriptions import RedisPublisher, RedisSubscription

logger = logging.getLogger(__name__)


class EngineRunner:
    """Generic harness that gives each engine a dedicated RedisSubscription.

    The subscription listener fires on_update directly into the engine —
    no queues, no polling, no sleep. The Redis ``async for message in
    pubsub.listen()`` IS the event loop.
    """

    def __init__(
        self,
        name: str,
        subscription: RedisSubscription,
        channels: list[str],
        event_type: type[BaseEvent],
        on_event: Callable[[Any], None],
        publisher: RedisPublisher | None = None,
    ) -> None:
        self.name = name
        self.subscription = subscription
        self.publisher = publisher
        self.channels = channels
        self.event_type = event_type
        self.on_event = on_event

    async def start(self) -> None:
        """Connect subscription, wire on_update, and run until cancelled."""
        await self.subscription.connect()

        for channel in self.channels:
            await self.subscription.subscribe(
                channel,
                event_type=self.event_type,
                on_update=self.on_event,
            )
            logger.info("Listening for %s on %s", self.event_type.__name__, channel)

        logger.info(
            "EngineRunner started — engine=%s, channels=%d",
            self.name,
            len(self.channels),
        )

        # The subscription listener task is already running.
        # Wait here until cancelled — the listener IS the event loop.
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("EngineRunner cancelled — engine=%s", self.name)

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("EngineRunner stopping — engine=%s", self.name)
        if self.publisher:
            self.publisher.close()
        await self.subscription.close()
        logger.info("EngineRunner stopped — engine=%s", self.name)
