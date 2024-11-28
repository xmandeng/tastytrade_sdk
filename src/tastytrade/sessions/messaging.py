import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from itertools import chain
from typing import Any, Dict, List, cast

from pydantic import ValidationError

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


@dataclass
class Message:
    type: str
    channel: int
    headers: dict[str, Any]
    data: list[Any]


class BaseMessageHandler(ABC):
    async def process_message(self, message: Message) -> None:
        await self.handle_message(message)

    @abstractmethod
    async def handle_message(self, message: Message) -> None:
        pass


class KeepaliveHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.debug("%s:Received", message.type)


class ErrorHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.error("%s:%s", message.headers.get("error"), message.headers.get("message"))


class SetupHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info("%s", message.type)


class AuthStateHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.headers.get("state"))


class ChannelOpenedHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        message_type = message.type
        channel = message.channel
        logger.info("%s:%s", message_type, channel)


class FeedConfigHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        message_type = message.type
        channel = message.channel
        data_format = message.headers.get("dataFormat")
        logger.info("%s:%s:%s", message_type, channel, data_format)


class FeedDataHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        raise NotImplementedError("%s should employ event_handlers", message.type)


class BaseEventHandler(ABC):
    channel: Channels

    async def queue_listener(self, queue: asyncio.Queue) -> None:

        logger.info(
            "Started queue listener for channel %s (%s)", self.channel.name, self.channel.value
        )

        while True:
            try:
                reply: dict[str, Any] = await asyncio.wait_for(queue.get(), timeout=1)

                logger.debug(
                    "Channel %s received message: %s", self.channel.value, reply.get("type")
                )
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

            except Exception as e:
                logger.error(
                    "Error in %s listener for channel %s: %s",
                    self.channel.name,
                    self.channel.value,
                    e,
                )
                break

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

                logger.info("Quotes handler for channel %s: %s", message.channel, quotes)

                return cast(EventList, quotes)

            except ValidationError as e:
                logger.error("Validation error in %s handler: %s", channel_name, e)
                raise e
            except Exception as e:
                logger.error("Unexpected error in %s handler: %s", channel_name, e)
                raise e


class TradesHandler(BaseEventHandler):
    channel = Channels.Trades

    async def handle_message(self, message: Message) -> ParsedEventType:
        logger.info("Trades handler for channel %s: %s", message.channel, message.data)
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
        logger.info("Greeks handler for channel %s: %s", message.channel, message.data)
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
        logger.info("Profile handler for channel %s: %s", message.channel, message.data)
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
        logger.info("Summary handler for channel %s: %s", message.channel, message.data)
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

    control_handlers: Dict[str, BaseMessageHandler] = {
        "SETUP": SetupHandler(),
        "AUTH_STATE": AuthStateHandler(),
        "CHANNEL_OPENED": ChannelOpenedHandler(),
        "FEED_CONFIG": FeedConfigHandler(),
        "FEED_DATA": FeedDataHandler(),  # Not implemented
        "KEEPALIVE": KeepaliveHandler(),
        "ERROR": ErrorHandler(),
    }

    async def handle_message(self, message: Message) -> None:
        """Read message headers and dispatch to the appropriate handler."""
        if handler := self.control_handlers.get(message.type):
            await handler.process_message(message)
        else:
            logger.warning("No handler found for message type: %s", message.type)


class MessageQueues:
    """Singleton QueueManager."""

    instance = None

    def __new__(cls):
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(self) -> None:
        # self.loop = asyncio.get_running_loop()

        self.queues: dict[int, asyncio.Queue] = {
            channel.value: asyncio.Queue() for channel in Channels
        }

        self.handlers: dict[int, BaseEventHandler] = {
            Channels.Control.value: ControlHandler(),
            Channels.Quotes.value: QuotesHandler(),
            Channels.Trades.value: TradesHandler(),
            Channels.Greeks.value: GreeksHandler(),
            Channels.Profile.value: ProfileHandler(),
            Channels.Summary.value: SummaryHandler(),
        }

        self.tasks: List[asyncio.Task] = [
            asyncio.create_task(
                listener.queue_listener(self.queues[listener.channel.value]),
                name=f"queue_listener_ch{listener.channel.value}_{listener.channel.name}",
            )
            for listener in self.handlers.values()
        ]

    async def cleanup(self) -> None:
        """Gracefully shutdown all queue listeners."""
        # self.shutdown.set()

        try:
            await asyncio.wait_for(
                asyncio.gather(*[queue.join() for queue in self.queues.values()]),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for queues to empty")

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("Message handlers stopped")
