import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

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

    async def put(self, channel: int, message: Any) -> None:
        await self.queues[channel].put(message)

    async def get(self, channel: int) -> Any:
        return await self.queues[channel].get()

    async def join(self, channel: int) -> None:
        await self.queues[channel].join()

    def task_done(self, channel: int) -> None:
        self.queues[channel].task_done()


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
        logger.info("%s:%s", message.data.get("type"), message.data.get("channel"))


class FeedConfigHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info(
            "%s:%s:%s",
            message.data.get("type"),
            message.data.get("channel"),
            message.data.get("dataFormat"),
        )


class FeedDataHandler(BaseMessageHandler):
    def __init__(self) -> None:
        self.parser = EventParser()

    async def handle_message(self, message: Message) -> None:
        pass


class MessageHandler:
    """Routes messages to appropriate handlers."""

    def __init__(self) -> None:
        self.queue_manager = MessageQueues()
        self.tasks: List[asyncio.Task] = []

        # Create a fixed pool of worker tasks per channel
        for channel in self.queue_manager.queues:
            task = asyncio.create_task(
                self.queue_listener(channel), name=f"queue_listener_ch{channel}"
            )
            self.tasks.append(task)

    async def cleanup(self) -> None:
        """Gracefully shutdown all queue listeners."""
        # Wait for queues to be empty
        for channel in self.queue_manager.queues:
            await self.queue_manager.queues[channel].join()

        # Then cancel the tasks
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def queue_listener(self, channel: int) -> None:
        while True:
            try:
                message = await self.queue_manager.queues[channel].get()
                logger.info(
                    "Received message on %s channel %s: %s",
                    Channels(channel).name,
                    channel,
                    message.get("type"),
                )
            except asyncio.CancelledError:
                logger.info("Queue listener stopped for channel %s", channel)
                break
            except Exception as e:
                logger.error("Error in queue listener for channel %s: %s", channel, e)
                break
            finally:
                self.queue_manager.queues[channel].task_done()

        self.handlers: Dict[str, BaseMessageHandler] = {
            "SETUP": SetupHandler(),
            "AUTH_STATE": AuthStateHandler(),
            "FEED_CONFIG": FeedConfigHandler(),
            "FEED_DATA": FeedDataHandler(),
            "KEEPALIVE": KeepaliveHandler(),
            "CHANNEL_OPENED": ChannelOpenedHandler(),
            "ERROR": ErrorHandler(),
        }

    async def route_message(self, raw_message: Dict[str, Any]) -> None:
        message = Message(
            type=raw_message.get("type", "UNKNOWN"),
            channel=raw_message.get("channel", 0),
            data=raw_message,
        )

        if handler := self.handlers.get(message.type):
            # sample message: {"type":"FEED_DATA","channel":1,"data":["Quote",["Quote",".SPXW241125P5990",10.5,10.7,4.0,24.0,"Quote",".SPXW241125P5980",5.1,5.3,96.0,55.0,"Quote",".SPXW241125P5970",2.4,2.5,63.0,116.0]]}
            await handler.process_message(message)
        else:
            logger.warning("No handler found for message type: %s", message.type)

    async def process_message_queue(self):
        while True:
            try:
                message = await self.queue_manager.queues[0].get()
                await self.process_message(message)
            except asyncio.CancelledError:
                logger.info("Queue processor stopped")
                break
            except Exception as e:
                logger.error("Unexpected error in queue processor: %s", e)

    async def process_message(self, message):
        try:
            await self.route_message(message)
        except Exception as e:
            logger.error("Error processing message: %s", e)
        finally:
            self.queue_manager.queues[0].task_done()
