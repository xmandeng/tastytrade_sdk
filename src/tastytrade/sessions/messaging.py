import asyncio
import logging
from abc import ABC
from itertools import chain
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Protocol, cast

import polars as pl
from pydantic import ValidationError

from tastytrade.exceptions import MessageProcessingError
from tastytrade.sessions.configurations import ChannelSpecs
from tastytrade.sessions.enumerations import Channels
from tastytrade.sessions.models import EventList, Message, ParsedEventType, SingleEventType

logger = logging.getLogger(__name__)

ROW_LIMIT = 100_000


class EventProcessor(Protocol):
    """Protocol for event processors"""

    name: str

    def process_event(self, event: SingleEventType) -> None: ...


class BaseEventProcessor:
    """Base processor that handles DataFrame storage"""

    name = "feed"

    def __init__(self):
        self.df = pl.DataFrame()

    def process_event(self, event: SingleEventType) -> None:
        self.df = self.df.vstack(pl.DataFrame([event]))

        if len(self.df) > 2 * ROW_LIMIT:
            self.df = self.df.tail(ROW_LIMIT)


class GreeksProcessor(BaseEventProcessor):
    name = "feed"

    def process_event(self, event: SingleEventType) -> None:
        self.df = self.df.vstack(pl.DataFrame([event])).unique(subset=["eventSymbol"], keep="last")

        if len(self.df) > 2 * ROW_LIMIT:
            self.df = self.df.tail(ROW_LIMIT)


class EventHandler(ABC):
    channel: Channels
    processor: Optional[BaseEventProcessor] = None

    stop_listener = asyncio.Event()
    diagnostic = True

    def __init__(self) -> None:
        channel_specs = ChannelSpecs.get_spec(self.channel) or ChannelSpecs.control
        self.channel = channel_specs.channel
        self.event = channel_specs.event_type
        self.fields = channel_specs.fields

        self.feed_processor = self.processor or BaseEventProcessor()
        self.processors: dict[str, EventProcessor] = {self.feed_processor.name: self.feed_processor}

    def add_processor(self, processor: EventProcessor) -> None:
        """Add new event processor"""
        self.processors.update({processor.name: processor})

    def remove_processor(self, processor: EventProcessor) -> None:
        """Remove event processor"""
        if processor.name in self.processors:
            del self.processors[processor.name]

    async def queue_listener(self, queue: asyncio.Queue) -> None:

        logger.info("Started %s listener on channel %s", self.channel, self.channel.value)

        while not self.stop_listener.is_set():
            try:
                reply: dict[str, Any] = await asyncio.wait_for(queue.get(), timeout=1)

                message = Message(
                    type=reply.get("type", "UNKNOWN"),
                    channel=reply.get("channel", 0),
                    headers=reply,
                    data=reply.get("data", {}),
                )

                try:
                    await asyncio.wait_for(self.handle_message(message), timeout=1)

                finally:
                    queue.task_done()

            except asyncio.TimeoutError:
                continue

            except asyncio.CancelledError:
                logger.info(
                    "%s listener stopped for channel %s", self.channel.name, self.channel.value
                )
                break

            except MessageProcessingError as e:
                logger.error("Message processing error in %s listener: %s", self.channel.name, e)
                if e.original_exception:
                    logger.debug("Original exception:", exc_info=e.original_exception)
                continue

            except Exception:
                logger.exception(
                    "Unhandled exception in %s listener on channel %s:",
                    self.channel.name,
                    self.channel.value,
                )
                continue

    async def handle_message(self, message: Message) -> ParsedEventType:
        events: List[SingleEventType] = []
        channel_name = Channels(message.channel).name

        data_filtered: Iterator[Any] = filter(lambda x: str(x) not in channel_name, message.data)
        flat_iterator: Iterator[Any] = iter(*chain(data_filtered))

        while True:
            try:
                data = {field: next(flat_iterator) for field in self.fields}
                event = self.event.value(**data)
                events.append(event)
                if channel_name == "Quotes":
                    pass

            except StopIteration:
                if self.diagnostic:
                    logger.debug(
                        "%s handler for channel %s: %s", self.channel.name, message.channel, events
                    )

                if remaining := [*flat_iterator]:
                    raise ValueError(
                        "Unexpected data in %s handler: [%s]", channel_name, ", ".join(remaining)
                    )

                for event in events:
                    for _, processor in self.processors.items():
                        processor.process_event(event)

                return cast(EventList, events)

            except ValidationError as e:
                logger.error("Validation error in %s handler: %s", channel_name, e)
                raise MessageProcessingError("Validation error in handler", e)

            except Exception as e:
                logger.exception("Unexpected error in %s handler:", self.channel.name)
                raise MessageProcessingError("Unexpected error occurred", e)


class QuotesHandler(EventHandler):
    channel = Channels.Quotes


class GreeksHandler(EventHandler):
    channel = Channels.Greeks
    processor = GreeksProcessor()


class TradesHandler(EventHandler):
    channel = Channels.Trades


class ProfileHandler(EventHandler):
    channel = Channels.Profile


class SummaryHandler(EventHandler):
    channel = Channels.Summary


class ControlMessageHandler:
    def __init__(self) -> None:
        self.control_handlers: Dict[str, Callable[[Message], Awaitable[None]]] = {
            "SETUP": self.handle_setup,
            "AUTH_STATE": self.handle_auth_state,
            "CHANNEL_OPENED": self.handle_channel_opened,
            "FEED_CONFIG": self.handle_feed_config,
            "KEEPALIVE": self.handle_keepalive,
            "ERROR": self.handle_error,
        }

    async def handle_message(self, message: Message) -> None:
        if self.control_handlers.get(message.type):
            await self.control_handlers[message.type](message)
        else:
            logger.warning("No handler found for message type: %s", message.type)

    async def handle_setup(self, message: Message) -> None:
        logger.info("%s", message.type)

    async def handle_auth_state(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.headers.get("state"))

    async def handle_channel_opened(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.channel)

    async def handle_feed_config(self, message: Message) -> None:
        data_format = message.headers.get("dataFormat", "")
        subscribed = ":SUBSCRIBED" if message.headers.get("eventFields") else ""
        logger.info("%s:%s:%s", message.type, message.channel, data_format + subscribed)

    async def handle_keepalive(self, message: Message) -> None:
        logger.debug("%s:Received", message.type)

    async def handle_error(self, message: Message) -> None:
        logger.error("%s:%s", message.headers.get("error"), message.headers.get("message"))


class ControlHandler(EventHandler):
    channel = Channels.Control
    handler = ControlMessageHandler()

    async def handle_message(self, message: Message) -> None:
        await self.handler.handle_message(message)


class MessageQueues:
    instance = None

    handlers: dict[str, EventHandler] = {
        "Control": ControlHandler(),
        "Quotes": QuotesHandler(),
        "Trades": TradesHandler(),
        "Greeks": GreeksHandler(),
        "Profile": ProfileHandler(),
        "Summary": SummaryHandler(),
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
            asyncio.create_task(self.drain_queue(Channels(channel)))
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
