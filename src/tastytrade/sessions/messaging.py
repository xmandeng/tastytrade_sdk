import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from itertools import chain
from typing import Any, Awaitable, Callable, Dict, List, cast

from pydantic import ValidationError

from tastytrade.exceptions import MessageProcessingError
from tastytrade.sessions.models import (
    EventList,
    GreeksEvent,
    ParsedEventType,
    ProfileEvent,
    QuoteEvent,
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


@dataclass
class Message:
    type: str
    channel: int
    headers: dict[str, Any]
    data: list[Any]


# Define a type alias for handler functions
HandlerFunction = Callable[[Message], Awaitable[None]]


class GenericMessageHandler:
    def __init__(self) -> None:
        self.handlers: Dict[str, HandlerFunction] = {
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

    @abstractmethod
    async def handle_message(self, message: Message) -> ParsedEventType:
        pass


class QuotesHandler(BaseEventHandler):
    channel = Channels.Quotes

    async def handle_message(self, message: Message) -> ParsedEventType:
        quotes: List[QuoteEvent] = []
        channel_name = Channels(message.channel).name

        feed = iter(*chain(filter(lambda x: x != "Quote", message.data)))

        while True:
            try:
                quotes.append(
                    QuoteEvent(
                        symbol=next(feed),
                        bid_price=next(feed),
                        ask_price=next(feed),
                        bid_size=next(feed),
                        ask_size=next(feed),
                    )
                )
            except StopIteration:
                if remaining := [*feed]:
                    raise ValueError(
                        "Unexpected data in %s handler: [%s]", channel_name, ", ".join(remaining)
                    )

                if self.diagnostic:
                    logger.debug("Quotes handler for channel %s: %s", message.channel, quotes)

                return cast(EventList, quotes)

            except ValidationError as e:
                logger.error("Validation error in %s handler: %s", channel_name, e)
                raise MessageProcessingError("Validation error in handler", e)

            except Exception as e:
                logger.exception("Unexpected error in %s handler:", self.channel.name)
                raise MessageProcessingError("Unexpected error occurred", e)


class TradesHandler(BaseEventHandler):
    channel = Channels.Trades

    async def handle_message(self, message: Message) -> ParsedEventType:
        logger.debug("Trades handler for channel %s: %s", message.channel, message.data)
        feed = iter(chain(filter(lambda x: x != "Trades", message.data)))

        trades: List[TradeEvent] = []

        while True:
            try:
                trades.append(
                    TradeEvent(
                        symbol=next(feed),
                        price=Decimal(next(feed)),
                        day_volume=Decimal(next(feed)),
                        size=Decimal(next(feed)),
                    )
                )
            except StopIteration:
                break
        return EventList(trades)


class GreeksHandler(BaseEventHandler):
    channel = Channels.Greeks

    async def handle_message(self, message: Message) -> ParsedEventType:
        logger.debug("Greeks handler for channel %s: %s", message.channel, message.data)
        feed = iter(chain(filter(lambda x: x != "Greeks", message.data)))

        greeks: List[GreeksEvent] = []

        while True:
            try:
                greeks.append(
                    GreeksEvent(
                        symbol=next(feed),
                        volatility=Decimal(next(feed)),
                        delta=Decimal(next(feed)),
                        gamma=Decimal(next(feed)),
                        theta=Decimal(next(feed)),
                        rho=Decimal(next(feed)),
                        vega=Decimal(next(feed)),
                    )
                )
            except StopIteration:
                break
        return EventList(greeks)


class ProfileHandler(BaseEventHandler):
    channel = Channels.Profile

    async def handle_message(self, message: Message) -> ParsedEventType:
        logger.debug("Profile handler for channel %s: %s", message.channel, message.data)
        feed = iter(chain(filter(lambda x: x != "Profile", message.data)))

        profile: List[ProfileEvent] = []

        while True:
            try:
                profile.append(
                    ProfileEvent(
                        symbol=next(feed),
                        description=next(feed),
                        short_sale_restriction=next(feed),
                        trading_status=next(feed),
                        status_reason=next(feed),
                        halt_start_time=next(feed),
                        halt_end_time=next(feed),
                        high_limit_price=Decimal(next(feed)),
                        low_limit_price=Decimal(next(feed)),
                        high_52_week_price=Decimal(next(feed)),
                        low_52_week_price=Decimal(next(feed)),
                    )
                )
            except StopIteration:
                break
        return EventList(profile)


class SummaryHandler(BaseEventHandler):
    channel = Channels.Summary

    async def handle_message(self, message: Message) -> ParsedEventType:
        logger.debug("Summary handler for channel %s: %s", message.channel, message.data)
        feed = iter(chain(filter(lambda x: x != "Summary", message.data)))

        summary: List[SummaryEvent] = []

        while True:
            try:
                summary.append(
                    SummaryEvent(
                        symbol=next(feed),
                        open_interest=Decimal(next(feed)),
                        day_open_price=Decimal(next(feed)),
                        day_high_price=Decimal(next(feed)),
                        day_low_price=Decimal(next(feed)),
                        prev_day_close_price=Decimal(next(feed)),
                    )
                )
            except StopIteration:
                break
        return EventList(summary)


class ControlHandler(BaseEventHandler):
    channel = Channels.Control

    def __init__(self):
        self.generic_handler = GenericMessageHandler()

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
