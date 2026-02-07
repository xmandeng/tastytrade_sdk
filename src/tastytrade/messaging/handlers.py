import asyncio
import logging
import time
from dataclasses import dataclass
from itertools import chain, islice
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Union

from pydantic import ValidationError

from tastytrade.common.exceptions import MessageProcessingError
from tastytrade.config.configurations import CHANNEL_SPECS
from tastytrade.config.enumerations import Channels, ReconnectReason
from tastytrade.connections.subscription import SubscriptionStore
from tastytrade.messaging.models.events import BaseEvent, CandleEvent
from tastytrade.messaging.models.messages import Message
from tastytrade.messaging.processors.default import BaseEventProcessor

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


class EventHandler:
    stop_listener = asyncio.Event()
    diagnostic = True

    def __init__(
        self,
        channel: Channels = Channels.Control,
        processor: Optional[BaseEventProcessor] = None,
        subscription_store: Optional[SubscriptionStore] = None,
    ) -> None:
        if channel not in CHANNEL_SPECS:
            channel = Channels.Control
            logger.error("Channel %s not found in channel_specs", channel)

        self.channel = channel
        self.processor = processor
        self.subscription_store = subscription_store

        self.event = CHANNEL_SPECS[self.channel].event_type
        self.fields = CHANNEL_SPECS[self.channel].fields

        self.metrics = QueueMetrics(channel=self.channel.value)

        self.feed_processor = self.processor or BaseEventProcessor()
        self.processors: dict[str, BaseEventProcessor] = {
            self.feed_processor.name: self.feed_processor
        }

        if self.channel == Channels.Candle:
            self.previous_candle: dict[str, CandleEvent] = {}

    def add_processor(self, processor: BaseEventProcessor) -> None:
        """Add new event processor"""
        self.processors.update({processor.name: processor})

    def remove_processor(self, processor: BaseEventProcessor) -> None:
        """Remove event processor"""
        if processor.name in self.processors:
            del self.processors[processor.name]

    def close_processors(self) -> None:
        """Close all registered processors, flushing any pending data."""
        for name, processor in self.processors.items():
            try:
                processor.close()
            except Exception as e:
                logger.warning("Error closing processor %s: %s", name, e)

    async def queue_listener(self, queue: asyncio.Queue) -> None:
        logger.info(
            "Started %s listener on channel %s", self.channel, self.channel.value
        )

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
                    logger.warning(
                        "Event skipped in %s listener: %s",
                        self.channel.name,
                        e,
                    )
                    if e.original_exception:
                        logger.debug(
                            "Original exception:", exc_info=e.original_exception
                        )
                    continue

                except Exception:
                    self.metrics.record_error()
                    logger.error(
                        "Unhandled exception in %s listener on channel %s:",
                        self.channel.name,
                        self.channel.value,
                    )
                    continue

        except asyncio.CancelledError:
            logger.info(
                "%s listener stopped for channel %s",
                self.channel.name,
                self.channel.value,
            )

            # Log final metrics
            logger.info(
                "Channel %s metrics - Total messages: %d, Errors: %d, Max queue size: %d",
                self.channel.value,
                self.metrics.total_messages,
                self.metrics.error_count,
                self.metrics.max_queue_size,
            )

    async def handle_message(
        self, message: Message
    ) -> Optional[Union[BaseEvent, List[BaseEvent]]]:
        events: List[BaseEvent] = []
        channel_name = Channels(message.channel).name

        try:
            # Filter and flatten the data once
            data_filtered: Iterator[Any] = filter(
                lambda x: str(x) not in channel_name, message.data
            )
            flat_data: Iterator[Any] = iter(*chain(data_filtered))

            # Process data in chunks based on # of fields
            field_tally = len(self.fields)
            while chunk := list(
                islice(flat_data, field_tally)
            ):  # islice is memory friendly
                if len(chunk) != field_tally:
                    logger.error(
                        "Incomplete data received on %s channel. Expected %d fields, got %d",
                        channel_name,
                        field_tally,
                        len(chunk),
                    )
                    break

                try:
                    data = dict(zip(self.fields, chunk, strict=False))
                    event = self.event.value(**data)
                    events.append(event)

                except ValidationError as e:
                    logger.warning(
                        "Skipped invalid event on %s channel: %s", channel_name, e
                    )
                    raise MessageProcessingError("Skipped invalid event", e) from e

                except Exception as e:
                    logger.error("Unexpected error in %s handler:", self.channel.name)
                    raise MessageProcessingError("Unexpected error occurred", e) from e

            # Check for any remaining data, indicating a problem
            if remaining := list(flat_data):
                logger.warning(
                    "Unexpected remaining data in %s handler: [%s]",
                    channel_name,
                    ", ".join(map(str, remaining)),
                )

            # Process events through registered processors
            for event in events:
                for _, processor in self.processors.items():
                    processor.process_event(event)

                # Update subscription status with last_update timestamp
                if self.subscription_store and hasattr(event, "eventSymbol"):
                    await self.subscription_store.update_subscription_status(
                        event.eventSymbol, {}
                    )

            if self.diagnostic:
                logger.debug(
                    "%s handler for channel %s processed %d events",
                    self.channel.name,
                    message.channel,
                    len(events),
                )

            return events if events else None

        except Exception as e:
            logger.warning("Skipped invalid event on %s channel", channel_name)
            raise MessageProcessingError("Skipped invalid event", e) from e


class ControlHandler(EventHandler):
    def __init__(
        self, reconnect_callback: Optional[Callable[[ReconnectReason], None]] = None
    ) -> None:
        super().__init__(channel=Channels.Control)
        self.reconnect_callback = reconnect_callback
        self.was_authorized = False  # Track if we've been authorized before
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
        state = message.headers.get("state", "UNKNOWN")
        if state == "AUTHORIZED":
            self.was_authorized = True
            logger.info("%s:%s", message.type, state)
        elif state == "UNAUTHORIZED":
            # Only trigger reconnect if we were previously authorized
            # Initial UNAUTHORIZED during handshake is expected
            if self.was_authorized:
                logger.error("DXLink AUTH_STATE: UNAUTHORIZED - triggering reconnect")
                if self.reconnect_callback:
                    self.reconnect_callback(ReconnectReason.AUTH_EXPIRED)
            else:
                logger.debug("AUTH_STATE: UNAUTHORIZED (initial handshake, expected)")
        else:
            logger.info("%s:%s", message.type, state)

    async def handle_channel_opened(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.channel)

    async def handle_feed_config(self, message: Message) -> None:
        data_format = message.headers.get("dataFormat", "")
        subscribed = ":SUBSCRIBED" if message.headers.get("eventFields") else ""
        logger.info("%s:%s:%s", message.type, message.channel, data_format + subscribed)

    async def handle_keepalive(self, message: Message) -> None:
        logger.debug("%s:Received", message.type)

    async def handle_error(self, message: Message) -> None:
        error_type = message.headers.get("error", "UNKNOWN")
        error_msg = message.headers.get("message", "")

        if error_type == "TIMEOUT":
            logger.error("DXLink %s: %s - triggering reconnect", error_type, error_msg)
            if self.reconnect_callback:
                self.reconnect_callback(ReconnectReason.TIMEOUT)
        elif error_type == "UNAUTHORIZED":
            logger.error("DXLink %s: %s - triggering reconnect", error_type, error_msg)
            if self.reconnect_callback:
                self.reconnect_callback(ReconnectReason.AUTH_EXPIRED)
        elif error_type == "UNSUPPORTED_PROTOCOL":
            logger.critical("DXLink UNSUPPORTED_PROTOCOL: %s - fatal error", error_msg)
        elif error_type in ("INVALID_MESSAGE", "BAD_ACTION"):
            logger.error("DXLink %s: %s - triggering reconnect", error_type, error_msg)
            if self.reconnect_callback:
                self.reconnect_callback(ReconnectReason.PROTOCOL_ERROR)
        else:
            logger.warning("DXLink %s: %s", error_type, error_msg)
