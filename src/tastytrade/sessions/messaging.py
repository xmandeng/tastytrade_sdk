import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from itertools import chain
from typing import Any, Awaitable, Callable, Dict, List, Union, cast

from pydantic import ValidationError

from tastytrade.sessions.models import (
    GreeksEvent,
    ProfileEvent,
    QuoteEvent,
    SummaryEvent,
    TradeEvent,
)

logger = logging.getLogger(__name__)

SingleEventType = Union[TradeEvent, QuoteEvent, GreeksEvent, ProfileEvent, SummaryEvent]
EventList = List[SingleEventType]
ParsedEventType = Union[SingleEventType, EventList]


@dataclass
class Message:
    type: str
    channel: int
    content: dict[str, Any]
    data: list[Any]


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
        logger.debug("%s:Received", message.type)


class ErrorHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.error("%s:%s", message.content.get("error"), message.content.get("message"))


class SetupHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info("%s", message.type)


class AuthStateHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.content.get("state"))


class ChannelOpenedHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        message_type = message.type
        channel = message.channel
        event = message.content.get("event")
        logger.info("%s:%s:%s", message_type, channel, event)


class FeedConfigHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        message_type = message.type
        channel = message.channel
        event = message.content.get("event")
        data_format = message.content.get("dataFormat")
        logger.info("%s:%s:%s:%s", message_type, channel, data_format, event)


class FeedDataHandler(BaseMessageHandler):
    async def handle_message(self, message: Message) -> None:
        raise NotImplementedError("%s should employ event_handlers", message.type)


class BaseEventHandler(ABC):
    async def process_message(self, message: Message) -> None:
        await self.handle_message(message)

    @abstractmethod
    async def handle_message(self, message: Message) -> ParsedEventType:
        pass


class QuotesHandler(BaseEventHandler):

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
                else:
                    break
            except ValidationError as e:
                logger.error("Validation error in %s handler: %s", channel_name, e)
            except Exception as e:
                logger.error("Unexpected error in %s handler: %s", channel_name, e)

            logger.info("Quotes handler for channel %s: %s", message.channel, quotes)

        return cast(EventList, quotes)


class TradesHandler(BaseEventHandler):

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


class MessageHandler:
    queue_manager = MessageQueues()
    tasks: List[asyncio.Task] = []
    shutdown = asyncio.Event()

    control_handlers: Dict[str, BaseMessageHandler] = {
        "SETUP": SetupHandler(),
        "AUTH_STATE": AuthStateHandler(),
        "CHANNEL_OPENED": ChannelOpenedHandler(),
        "FEED_CONFIG": FeedConfigHandler(),
        "FEED_DATA": FeedDataHandler(),  # Not implemented
        "KEEPALIVE": KeepaliveHandler(),
        "ERROR": ErrorHandler(),
    }

    event_handlers = {
        Channels.Trades.name: TradesHandler(),
        Channels.Quotes.name: QuotesHandler(),
        Channels.Greeks.name: GreeksHandler(),
        Channels.Profile.name: ProfileHandler(),
        Channels.Summary.name: SummaryHandler(),
    }

    def __init__(self) -> None:
        for channel in self.queue_manager.queues:
            handler = self.control_handler if channel == 0 else self.event_handler

            task = asyncio.create_task(
                self.queue_listener(channel, handler), name=f"queue_listener_ch{channel}"
            )
            self.tasks.append(task)

    async def queue_listener(
        self, channel: int, handler: Callable[[Message], Awaitable[None]]
    ) -> None:
        while not self.shutdown.is_set():
            try:
                reply = await asyncio.wait_for(self.queue_manager.queues[channel].get(), timeout=1)

                message_type = reply.get("type", "UNKNOWN")
                queue_name = reply.get("channel") if message_type == "FEED_DATA" else 0
                data = reply.get("data", {})
                content: dict[str, Any] = reply.copy()
                content.pop("data", None)
                content.pop("type", None)

                message = Message(
                    type=message_type,
                    channel=queue_name,
                    data=data,
                    content=content,
                )

                await asyncio.wait_for(handler(message), timeout=1)

            except asyncio.TimeoutError:
                continue  # TODO - Check shutdown event
            except asyncio.CancelledError:
                logger.info("Queue listener stopped for channel %s", channel)
                break
            except Exception as e:
                logger.error("Error in queue listener for channel %s: %s", channel, e)
                break
            finally:
                self.queue_manager.queues[channel].task_done()

    async def control_handler(self, message: Message) -> None:
        """Read message headers and dispatch to the appropriate handler."""
        if handler := self.control_handlers.get(message.type):
            await handler.process_message(message)
        else:
            logger.warning("No handler found for message type: %s", message.type)

    async def event_handler(self, message: Message) -> None:
        """Read message headers and dispatch to the appropriate handler."""
        event_type = Channels(message.channel).name

        if handler := self.event_handlers.get(event_type):
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
