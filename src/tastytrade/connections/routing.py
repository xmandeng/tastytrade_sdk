import asyncio
import logging
from typing import Callable, List, Optional, Protocol

from tastytrade.config.enumerations import Channels
from tastytrade.connections.subscription import SubscriptionStore
from tastytrade.messaging.handlers import ControlHandler, EventHandler
from tastytrade.messaging.processors.default import (
    CandleEventProcessor,
    LatestEventProcessor,
)

logger = logging.getLogger(__name__)


ReconnectCallback = Callable[[str], None]


class Websocket(Protocol):
    queues: dict[int, asyncio.Queue]


class MessageRouter:
    instance = None
    queues: dict[int, asyncio.Queue] = {}

    # Default handlers (without reconnect callback)
    default_handlers: dict[Channels, EventHandler] = {
        Channels.Control: ControlHandler(),
        Channels.Quote: EventHandler(Channels.Quote, processor=LatestEventProcessor()),
        Channels.Trade: EventHandler(Channels.Trade),
        Channels.Greeks: EventHandler(
            Channels.Greeks, processor=LatestEventProcessor()
        ),
        Channels.Profile: EventHandler(
            Channels.Profile, processor=LatestEventProcessor()
        ),
        Channels.Summary: EventHandler(
            Channels.Summary, processor=LatestEventProcessor()
        ),
        Channels.Candle: EventHandler(
            Channels.Candle, processor=CandleEventProcessor()
        ),
    }

    def __new__(cls, *args: object, **kwargs: object) -> "MessageRouter":
        if not hasattr(cls, "instance") or cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(
        self,
        websocket: Websocket,
        reconnect_callback: Optional[ReconnectCallback] = None,
        subscription_store: Optional[SubscriptionStore] = None,
    ) -> None:
        # Create handler dict with reconnect-aware ControlHandler
        # Pass subscription_store to data handlers for last_update tracking
        self.handler: dict[Channels, EventHandler] = {
            Channels.Control: ControlHandler(reconnect_callback=reconnect_callback),
            Channels.Quote: EventHandler(
                Channels.Quote,
                processor=LatestEventProcessor(),
                subscription_store=subscription_store,
            ),
            Channels.Trade: EventHandler(
                Channels.Trade, subscription_store=subscription_store
            ),
            Channels.Greeks: EventHandler(
                Channels.Greeks,
                processor=LatestEventProcessor(),
                subscription_store=subscription_store,
            ),
            Channels.Profile: EventHandler(
                Channels.Profile,
                processor=LatestEventProcessor(),
                subscription_store=subscription_store,
            ),
            Channels.Summary: EventHandler(
                Channels.Summary,
                processor=LatestEventProcessor(),
                subscription_store=subscription_store,
            ),
            Channels.Candle: EventHandler(
                Channels.Candle,
                processor=CandleEventProcessor(),
                subscription_store=subscription_store,
            ),
        }
        # Start queue listeners
        self.tasks: List[asyncio.Task] = [
            asyncio.create_task(
                handler.queue_listener(websocket.queues[handler.channel.value]),
                name=f"queue_listener_ch{handler.channel.value}_{handler.channel.name}",
            )
            for _, handler in self.handler.items()
        ]

    async def close(self) -> None:
        logger.info("Initiating cleanup...")

        for _, handler in self.handler.items():
            handler.stop_listener.set()

        drain_tasks = [
            asyncio.create_task(
                self.drain_queue(Channels(channel)),
                name=f"drain_queue__ch{channel}",
            )
            for channel in self.queues.keys()
        ]
        await asyncio.gather(*drain_tasks, return_exceptions=True)

        for task in self.tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("Task %s cancelled", task.get_name())

        for _, handler in self.handler.items():
            handler.stop_listener.clear()

        logger.info("Cleanup completed")

    async def drain_queue(self, channel: Channels) -> None:
        queue = self.queues[channel.value]
        logger.debug("Draining %s queue on channel %s", channel.name, channel.value)

        try:
            while not queue.empty():
                try:
                    message = queue.get_nowait()
                    logger.debug(
                        "Drained %s messages on channel %s: %s",
                        channel.name,
                        channel.value,
                        message,
                    )
                    queue.task_done()
                except asyncio.QueueEmpty:
                    logger.warning(
                        "Attempted to drain an already empty %s queue for channel %s",
                        channel.name,
                        channel.value,
                    )
                    break
        except Exception as e:
            logger.error(
                "Error draining %s queue on channel %s: %s",
                channel.name,
                channel.value,
                e,
            )

        logger.debug("%s channel %s drained", channel.name, channel.value)
