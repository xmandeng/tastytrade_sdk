import asyncio
import logging
from typing import List, Protocol

from tastytrade.config.enumerations import Channels
from tastytrade.messaging.handlers import ControlHandler, EventHandler
from tastytrade.messaging.processors.default import (
    CandleEventProcessor,
    EventProcessor,
    LatestEventProcessor,
)

logger = logging.getLogger(__name__)


class Websocket(Protocol):
    queues: dict[int, asyncio.Queue]


class MessageRouter:
    instance = None
    queues: dict[int, asyncio.Queue] = {}

    handler: dict[Channels, EventHandler] = {
        Channels.Control: ControlHandler(),
        Channels.Quote: EventHandler(Channels.Quote, processor=LatestEventProcessor()),
        Channels.Trade: EventHandler(Channels.Trade),
        Channels.Greeks: EventHandler(Channels.Greeks, processor=LatestEventProcessor()),
        Channels.Profile: EventHandler(Channels.Profile, processor=LatestEventProcessor()),
        Channels.Summary: EventHandler(Channels.Summary, processor=LatestEventProcessor()),
        Channels.Candle: EventHandler(Channels.Candle, processor=CandleEventProcessor()),
    }

    def __new__(cls, *args: object, **kwargs: object) -> "MessageRouter":
        if not hasattr(cls, "instance") or cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self, websocket: Websocket) -> None:

        # Start queue listeners
        self.tasks: List[asyncio.Task] = [
            asyncio.create_task(
                handler.queue_listener(websocket.queues[handler.channel.value]),
                name=f"queue_listener_ch{handler.channel.value}_{handler.channel.name}",
            )
            for _, handler in self.handler.items()
        ]

    def add_processor(self, processor: EventProcessor) -> None:
        for handler in self.handler.values():
            handler.add_processor(processor)

    def remove_processor(self, processor: EventProcessor) -> None:
        for handler in self.handler.values():
            handler.remove_processor(processor)

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
                "Error draining %s queue on channel %s: %s", channel.name, channel.value, e
            )

        logger.debug("%s channel %s drained", channel.name, channel.value)
