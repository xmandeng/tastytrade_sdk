import asyncio
import logging
from abc import ABC
from enum import Enum
from itertools import chain
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Type, cast

from pydantic import ValidationError

from tastytrade.exceptions import MessageProcessingError
from tastytrade.sessions.configurations import ChannelSpecs
from tastytrade.sessions.types import (
    EventList,
    GreeksEvent,
    Message,
    ParsedEventType,
    ProfileEvent,
    QuoteEvent,
    SingleEventType,
    SummaryEvent,
    TradeEvent,
)

logger = logging.getLogger(__name__)


class Channels(Enum):
    Control = 0
    Trades = 1
    Quotes = 3
    Greeks = 5
    Profile = 7
    Summary = 9
    Errors = 99


class EventHandler(ABC):
    channel: Channels
    event: Type[QuoteEvent | GreeksEvent | ProfileEvent | SummaryEvent | TradeEvent]
    fields: List[str]

    stop_listener = asyncio.Event()

    diagnostic = True

    async def queue_listener(self, queue: asyncio.Queue) -> None:

        logger.info("Started %s listener on channel %s", self.channel.name, self.channel.value)

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
                event_data = {field: next(flat_iterator) for field in self.fields}
                if channel_name == "Quotes":
                    pass
                event = self.event(**event_data)
                events.append(event)
            except StopIteration:
                if remaining := [*flat_iterator]:
                    raise ValueError(
                        "Unexpected data in %s handler: [%s]", channel_name, ", ".join(remaining)
                    )

                if self.diagnostic:
                    logger.debug(
                        "%s handler for channel %s: %s", self.channel.name, message.channel, events
                    )

                return cast(EventList, events)

            except ValidationError as e:
                logger.error("Validation error in %s handler: %s", channel_name, e)
                raise MessageProcessingError("Validation error in handler", e)

            except Exception as e:
                logger.exception("Unexpected error in %s handler:", self.channel.name)
                raise MessageProcessingError("Unexpected error occurred", e)


class QuotesHandler(EventHandler):
    channel = Channels.Quotes
    event = QuoteEvent
    fields = ChannelSpecs.QUOTES.fields


class TradesHandler(EventHandler):
    channel = Channels.Trades
    event = TradeEvent
    fields = ChannelSpecs.TRADES.fields


class GreeksHandler(EventHandler):
    channel = Channels.Greeks
    event = GreeksEvent
    fields = ChannelSpecs.GREEKS.fields


class ProfileHandler(EventHandler):
    channel = Channels.Profile
    event = ProfileEvent
    fields = ChannelSpecs.PROFILE.fields


class SummaryHandler(EventHandler):
    channel = Channels.Summary
    event = SummaryEvent
    fields = ChannelSpecs.SUMMARY.fields


class ControlMessageHandler:
    def __init__(self) -> None:
        self.handlers: Dict[str, Callable[[Message], Awaitable[None]]] = {
            "SETUP": self.handle_setup,
            "AUTH_STATE": self.handle_auth_state,
            "CHANNEL_OPENED": self.handle_channel_opened,
            "FEED_CONFIG": self.handle_feed_config,
            "KEEPALIVE": self.handle_keepalive,
            "ERROR": self.handle_error,
        }

    async def handle_message(self, message: Message) -> None:
        if control_handler := self.handlers.get(message.type):
            await control_handler(message)
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

    handlers: list[EventHandler] = [
        ControlHandler(),
        QuotesHandler(),
        TradesHandler(),
        GreeksHandler(),
        ProfileHandler(),
        SummaryHandler(),
    ]

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
            for listener in self.handlers
        ]

    async def cleanup(self) -> None:
        logger.info("Initiating cleanup...")

        for handler in self.handlers:
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

        for handler in self.handlers:
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
