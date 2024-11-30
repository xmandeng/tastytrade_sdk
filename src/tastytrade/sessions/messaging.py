import asyncio
import logging
from abc import ABC
from enum import Enum
from itertools import chain
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Type, cast

from pydantic import ValidationError

from tastytrade.exceptions import MessageProcessingError
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


class GenericMessageHandler:
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
        handler = self.handlers.get(message.type)
        if handler:
            await handler(message)
        else:
            logger.warning("No handler found for message type: %s", message.type)

    async def handle_setup(self, message: Message) -> None:
        logger.info("%s", message.type)

    async def handle_auth_state(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.headers.get("state"))

    async def handle_channel_opened(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.channel)

    async def handle_feed_config(self, message: Message) -> None:
        data_format = message.headers.get("dataFormat")
        logger.info("%s:%s:%s", message.type, message.channel, data_format)

    async def handle_keepalive(self, message: Message) -> None:
        logger.debug("%s:Received", message.type)

    async def handle_error(self, message: Message) -> None:
        logger.error("%s:%s", message.headers.get("error"), message.headers.get("message"))


class BaseEventHandler(ABC):
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


class QuotesHandler(BaseEventHandler):
    channel = Channels.Quotes
    event = QuoteEvent
    fields = ["symbol", "bid_price", "ask_price", "bid_size", "ask_size"]


class TradesHandler(BaseEventHandler):
    channel = Channels.Trades
    event = TradeEvent
    fields = ["symbol", "price", "size", "day_volume"]


class GreeksHandler(BaseEventHandler):
    channel = Channels.Greeks
    event = GreeksEvent
    fields = ["symbol", "volatility", "delta", "gamma", "theta", "rho", "vega"]


class ProfileHandler(BaseEventHandler):
    channel = Channels.Profile
    event = ProfileEvent
    fields = [
        "symbol",
        "description",
        "short_sale_restriction",
        "trading_status",
        "status_reason",
        "halt_start_time",
        "halt_end_time",
        "high_limit_price",
        "low_limit_price",
        "high_52_week_price",
        "low_52_week_price",
    ]


class SummaryHandler(BaseEventHandler):
    channel = Channels.Summary
    event = SummaryEvent
    fields = [
        "symbol",
        "open_interest",
        "day_open_price",
        "day_high_price",
        "day_low_price",
        "prev_day_close_price",
    ]


class ControlHandler(BaseEventHandler):
    channel = Channels.Control
    generic_handler = GenericMessageHandler()

    async def handle_message(self, message: Message) -> None:
        await self.generic_handler.handle_message(message)


class MessageQueues:
    instance = None

    def __new__(cls):
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(self) -> None:
        # Create Websocket queues for each channel
        self.queues: dict[int, asyncio.Queue] = {
            channel.value: asyncio.Queue() for channel in Channels if channel != Channels.Errors
        }

        # Associate handlers with channels
        self.handlers: dict[int, BaseEventHandler] = {
            Channels.Control.value: ControlHandler(),
            Channels.Quotes.value: QuotesHandler(),
            Channels.Trades.value: TradesHandler(),
            Channels.Greeks.value: GreeksHandler(),
            Channels.Profile.value: ProfileHandler(),
            Channels.Summary.value: SummaryHandler(),
        }

        # Start queue listeners
        self.tasks: List[asyncio.Task] = [
            asyncio.create_task(
                listener.queue_listener(self.queues[listener.channel.value]),
                name=f"queue_listener_ch{listener.channel.value}_{listener.channel.name}",
            )
            for listener in self.handlers.values()
        ]

    async def cleanup(self) -> None:
        logger.info("Initiating cleanup...")

        for handler in self.handlers.values():
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

        for handler in self.handlers.values():
            handler.stop_listener.clear()

        logger.info("Cleanup completed")

    async def drain_queue(self, channel: Channels) -> None:
        queue = self.queues[channel.value]
        logger.debug("Draining %s queue on channel %s", channel.name, channel.value)

        try:
            while not queue.empty():
                try:
                    message = queue.get_nowait()  # Non-blocking get
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
