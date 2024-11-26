import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List

from tastytrade.sessions.parsers import EventParser

logger = logging.getLogger(__name__)


@dataclass
class Message:
    type: str
    channel: int
    data: Dict[str, Any]


class Channels(Enum):
    Control = 0
    Trades = 1
    Quotes = 3
    Greeks = 5
    Profile = 7
    Summary = 9


class MessageQueues:
    """MessageQueues is a singleton QueueManager."""

    instance = None

    def __new__(cls):
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(self) -> None:
        self.queues: dict[int, asyncio.Queue] = {queue.value: asyncio.Queue() for queue in Channels}


class BaseMessageHandler(ABC):
    async def process_message(self, message: Message) -> None:
        await self.handle_message(message)

    @abstractmethod
    async def handle_message(self, message: Message) -> None:
        pass


class KeepaliveHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info("%s:Received", message.type)


class ErrorHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.error("%s:%s", message.data.get("error"), message.data.get("message"))


class SetupHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info("%s", message.type)


class AuthStateHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.data.get("state"))


class ChannelOpenedHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        message_type = message.data.get("type")
        channel = Channels(message.data.get("channel")).value
        event = Channels(message.data.get("channel")).name
        logger.info("%s:%s:%s", message_type, channel, event)


class FeedConfigHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        message_type = message.data.get("type")
        channel = Channels(message.data.get("channel")).value
        event = Channels(message.data.get("channel")).name
        data_format = message.data.get("dataFormat")
        logger.info("%s:%s:%s:%s", message_type, channel, data_format, event)


class FeedDataHandler(BaseMessageHandler):
    def __init__(self) -> None:
        self.parser = EventParser()

    async def handle_message(self, message: Message) -> None:
        pass


class MessageHandler:
    queue_manager = MessageQueues()
    tasks: List[asyncio.Task] = []
    shutdown = asyncio.Event()

    control_handlers: Dict[str, BaseMessageHandler] = {
        "SETUP": SetupHandler(),
        "AUTH_STATE": AuthStateHandler(),
        "FEED_CONFIG": FeedConfigHandler(),
        "FEED_DATA": FeedDataHandler(),
        "KEEPALIVE": KeepaliveHandler(),
        "CHANNEL_OPENED": ChannelOpenedHandler(),
        "ERROR": ErrorHandler(),
    }

    event_handlers: Dict[str, BaseMessageHandler] = {}

    def __init__(self) -> None:
        for channel in self.queue_manager.queues:
            router = self.control_handler if channel == 0 else self.event_handler

            task = asyncio.create_task(
                self.queue_listener(channel, router), name=f"queue_listener_ch{channel}"
            )
            self.tasks.append(task)

    async def queue_listener(
        self, channel: int, router: Callable[[Message], Awaitable[None]]
    ) -> None:
        while not self.shutdown.is_set():
            try:
                reply = await asyncio.wait_for(self.queue_manager.queues[channel].get(), timeout=1)

                message = Message(
                    type=reply.get("type", "UNKNOWN"),
                    channel=reply.get("channel", 0),
                    data=reply,
                )

                await asyncio.wait_for(router(message), timeout=1)

                self.queue_manager.queues[channel].task_done()

            except asyncio.TimeoutError:
                continue  # TODO - Check shutdown event
            except asyncio.CancelledError:
                logger.info("Queue listener stopped for channel %s", channel)
                break
            except Exception as e:
                logger.error("Error in queue listener for channel %s: %s", channel, e)
                break

    async def event_handler(self, message: Message) -> None:
        """Read message payload and parse using Channels enum.

        # TODO - Parse event using Channels enum

        Sample message:

        {
            "type": "FEED_DATA",
            "channel": 3,
            "data": [
                "Quote",
                [
                    "Quote",".SPXW241125P5990",10.5,10.7,4.0,24.0,
                    "Quote",".SPXW241125P5980",5.1,5.3,96.0,55.0,
                    "Quote",".SPXW241125P5970",2.4,2.5,63.0,116.0,
                ],
            ],
        }

        """
        logger.info("Event handler for channel %s: %s", message.channel, message.data)

    async def control_handler(self, message: Message) -> None:
        """Read message headers and dispatch to the appropriate handler."""
        if handler := self.control_handlers.get(message.type):
            await handler.process_message(message)
        else:
            logger.warning("No handler found for message type: %s", message.type)

    async def cleanup(self) -> None:
        """Gracefully shutdown all queue listeners."""
        self.shutdown.set()

        try:
            await asyncio.wait_for(
                asyncio.gather(*[queue.join() for queue in self.queue_manager.queues.values()]),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for queues to empty")

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("Message handlers stopped")
