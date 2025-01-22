import asyncio
import logging
import time
from dataclasses import dataclass
from itertools import chain
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Protocol, Union, cast

import polars as pl
from pydantic import ValidationError

from tastytrade.exceptions import MessageProcessingError
from tastytrade.sessions.configurations import CHANNEL_SPECS
from tastytrade.sessions.enumerations import Channels
from tastytrade.sessions.models import BaseEvent, Message

logger = logging.getLogger(__name__)

ROW_LIMIT = 100_000


@dataclass
class QueueMetrics:
    channel: int
    total_messages: int = 0
    error_count: int = 0
    last_message_time: float = 0
    max_queue_size: int = 0

    def update(self, queue_size: int) -> None:
        self.total_messages += 1
        self.last_message_time = time.time()
        self.max_queue_size = max(self.max_queue_size, queue_size)

    def record_error(self) -> None:
        self.error_count += 1


class EventProcessor(Protocol):
    """Protocol for event processors"""

    name: str

    def process_event(self, event: BaseEvent) -> None: ...


class BaseEventProcessor:
    """Base processor that handles DataFrame storage"""

    name = "feed"

    def __init__(self):
        self.df = pl.DataFrame()

    def process_event(self, event: BaseEvent) -> None:
        self.df = self.df.vstack(pl.DataFrame([event]))

        if len(self.df) > 2 * ROW_LIMIT:
            self.df = self.df.tail(ROW_LIMIT)


class LatestEventProcessor(BaseEventProcessor):
    name = "feed"

    def process_event(self, event: BaseEvent) -> None:
        self.df = self.df.vstack(pl.DataFrame([event])).unique(subset=["eventSymbol"], keep="last")


class EventHandler:

    stop_listener = asyncio.Event()
    diagnostic = True

    def __init__(
        self, channel: Channels = Channels.Control, processor: Optional[BaseEventProcessor] = None
    ) -> None:

        if channel not in CHANNEL_SPECS:
            channel = Channels.Control
            logger.error("Channel %s not found in channel_specs", channel)

        self.channel = channel
        self.processor = processor

        self.event = CHANNEL_SPECS[self.channel].event_type
        self.fields = CHANNEL_SPECS[self.channel].fields

        self.metrics = QueueMetrics(channel=self.channel.value)

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

        try:
            while not self.stop_listener.is_set():
                try:
                    reply = await queue.get()
                    self.metrics.update(queue.qsize())

                    message = Message(
                        type=reply.get("type", "UNKNOWN"),
                        channel=reply.get("channel", 0),
                        headers=reply,
                        data=reply.get("data", {}),
                    )

                    try:
                        await self.handle_message(message)
                    finally:
                        queue.task_done()

                except MessageProcessingError as e:
                    self.metrics.record_error()
                    logger.error(
                        "Message processing error in %s listener: %s", self.channel.name, e
                    )
                    if e.original_exception:
                        logger.debug("Original exception:", exc_info=e.original_exception)
                    continue

                except Exception:
                    self.metrics.record_error()
                    logger.exception(
                        "Unhandled exception in %s listener on channel %s:",
                        self.channel.name,
                        self.channel.value,
                    )
                    continue

        except asyncio.CancelledError:
            logger.info("%s listener stopped for channel %s", self.channel.name, self.channel.value)

            # Log final metrics
            logger.info(
                "Channel %s metrics - Total messages: %d, Errors: %d, Max queue size: %d",
                self.channel.value,
                self.metrics.total_messages,
                self.metrics.error_count,
                self.metrics.max_queue_size,
            )

    async def handle_message(self, message: Message) -> Optional[Union[BaseEvent, List[BaseEvent]]]:
        events: List[BaseEvent] = []
        channel_name = Channels(message.channel).name

        data_filtered: Iterator[Any] = filter(lambda x: str(x) not in channel_name, message.data)
        flat_iterator: Iterator[Any] = iter(*chain(data_filtered))

        while True:
            try:
                data = {field: next(flat_iterator) for field in self.fields}
                event = self.event.value(**data)
                events.append(event)

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

                return cast(List[BaseEvent], events)

            except ValidationError as e:
                logger.error("Validation error in %s handler: %s", channel_name, e)
                raise MessageProcessingError("Validation error in handler", e)

            except Exception as e:
                logger.exception("Unexpected error in %s handler:", self.channel.name)
                raise MessageProcessingError("Unexpected error occurred", e)


class ControlHandler(EventHandler):

    def __init__(self) -> None:
        super().__init__(channel=Channels.Control)
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
