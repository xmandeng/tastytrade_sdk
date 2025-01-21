import asyncio
import logging
from typing import List, Protocol

from tastytrade.sessions.enumerations import Channels
from tastytrade.sessions.handlers import ControlHandler, EventHandler, LatestEventProcessor

logger = logging.getLogger(__name__)


class Websocket(Protocol):
    queues: dict[int, asyncio.Queue]


class MessageDispatcher:
    instance = None

    handlers: dict[str, EventHandler] = {
        "Control": ControlHandler(),
        "Quote": EventHandler(Channels.Quote),
        "Trade": EventHandler(Channels.Trade),
        "Greeks": EventHandler(Channels.Greeks, processor=LatestEventProcessor()),
        "Profile": EventHandler(Channels.Profile, processor=LatestEventProcessor()),
        "Summary": EventHandler(Channels.Summary, processor=LatestEventProcessor()),
    }

    def __new__(cls):
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(self) -> None:
        # Create Websocket queues for each channel
        self.queues: dict[int, asyncio.Queue] = {
            channel.value: asyncio.Queue() for channel in Channels if channel != Channels.Errors
        }

        # Start queue listeners
        self.tasks: List[asyncio.Task] = [
            asyncio.create_task(
                listener.queue_listener(self.queues[listener.channel.value]),
                name=f"queue_listener_ch{listener.channel.value}_{listener.channel.name}",
            )
            for _, listener in self.handlers.items()
        ]

    async def cleanup(self) -> None:
        logger.info("Initiating cleanup...")

        for _, handler in self.handlers.items():
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

        for _, handler in self.handlers.items():
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
