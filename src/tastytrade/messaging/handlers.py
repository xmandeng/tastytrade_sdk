import asyncio
import logging
import time
from dataclasses import dataclass
from itertools import chain, islice
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Union, cast

from pydantic import ValidationError

from tastytrade.common.exceptions import MessageProcessingError
from tastytrade.config.configurations import CHANNEL_SPECS
from tastytrade.config.enumerations import Channels, ReconnectReason
from tastytrade.connections.signals import ReconnectSignal
from tastytrade.connections.subscription import SubscriptionStore
from tastytrade.messaging.models.events import BaseEvent, CandleEvent
from tastytrade.messaging.models.messages import Message
from tastytrade.messaging.processors.default import BaseEventProcessor

logger = logging.getLogger(__name__)

# Coalescing drain (TT-164 phase 2): a listener iteration consumes at most
# this many queued replies. Bounds the work between task_done batches so a
# deep backlog is worked in slices, without ever delaying a current channel
# (an empty queue simply yields a batch of one).
DRAIN_SLICE = 500

# last_update stamping is throttled to once per symbol per second — its
# readers (reconnect start-date, health display) are second-granularity.
STATUS_STAMP_SECONDS = 1.0

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
    diagnostic = True

    def __init__(
        self,
        channel: Channels = Channels.Control,
        processor: Optional[BaseEventProcessor] = None,
        subscription_store: Optional[SubscriptionStore] = None,
    ) -> None:
        self.stop_listener = asyncio.Event()
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

        if self.channel in (Channels.Candle, Channels.CandleFast):
            self.previous_candle: dict[str, CandleEvent] = {}

        # Throttled last_update stamping (TT-164 phase 2): monotonic time of
        # the most recent stamp per symbol.
        self.last_status_stamp: dict[str, float] = {}

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
                # Coalescing drain (TT-164 phase 2): take everything already
                # queued, bounded by DRAIN_SLICE, and process it as one batch.
                # An empty queue yields a batch of one — per-event latency is
                # unchanged on a current channel; only a backlog batches.
                replies = [await queue.get()]
                while len(replies) < DRAIN_SLICE:
                    try:
                        replies.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                self.metrics.update(queue.qsize())

                try:
                    await self.handle_batch(replies)
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
                except Exception:
                    self.metrics.record_error()
                    logger.error(
                        "Unhandled exception in %s listener on channel %s:",
                        self.channel.name,
                        self.channel.value,
                    )
                finally:
                    for _ in replies:
                        queue.task_done()

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

    @staticmethod
    def make_message(reply: dict) -> Message:
        return Message(
            type=reply.get("type", "UNKNOWN"),
            channel=reply.get("channel", 0),
            headers=reply,
            data=reply.get("data", {}),
        )

    async def handle_batch(self, replies: List[dict]) -> None:
        """Parse a slice of raw replies, then dispatch all events at once.

        Parse failures skip that reply (recorded, logged) without dropping
        the rest of the slice — the same per-message skip semantics the
        serial loop had. ControlHandler overrides this with per-message
        handling; control messages are commands, not data events.
        """
        events: List[BaseEvent] = []
        for reply in replies:
            try:
                events.extend(self.parse_events(self.make_message(reply)))
            except MessageProcessingError as e:
                self.metrics.record_error()
                logger.warning("Event skipped in %s listener: %s", self.channel.name, e)
        if events:
            await self.dispatch_batch(events)

    async def dispatch_batch(self, events: List[BaseEvent]) -> None:
        """One processor call for the whole batch, then throttled stamps.

        Supports both sync and async processors — async processors (the
        RedisEventProcessor pipeline) return a coroutine that is awaited.
        """
        for _, processor in self.processors.items():
            result = processor.process_events(events)  # type: ignore[func-returns-value]
            if asyncio.iscoroutine(result):
                await result  # type: ignore[arg-type]
        await self.touch_subscriptions(events)

    async def touch_subscriptions(self, events: List[BaseEvent]) -> None:
        """Stamp last_update at most once per symbol per second.

        The stamp's readers (reconnect start-date derivation, health display)
        work at second granularity or coarser; per-event stamping cost two
        Redis round-trips per event for no added information.
        """
        if not self.subscription_store:
            return
        now = time.monotonic()
        for symbol in {e.eventSymbol for e in events if hasattr(e, "eventSymbol")}:
            if now - self.last_status_stamp.get(symbol, 0.0) >= STATUS_STAMP_SECONDS:
                self.last_status_stamp[symbol] = now
                await self.subscription_store.update_subscription_status(symbol, {})

    async def handle_message(
        self, message: Message
    ) -> Optional[Union[BaseEvent, List[BaseEvent]]]:
        """Parse one message and dispatch its events (compatibility path)."""
        events = self.parse_events(message)
        if events:
            try:
                await self.dispatch_batch(events)
            except Exception as e:
                logger.warning(
                    "Skipped invalid event on %s channel: %s",
                    Channels(message.channel).name,
                    e,
                )
                raise MessageProcessingError("Skipped invalid event", e) from e
        if self.diagnostic:
            logger.debug(
                "%s handler for channel %s processed %d events",
                self.channel.name,
                message.channel,
                len(events),
            )
        return events if events else None

    def parse_events(self, message: Message) -> List[BaseEvent]:
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
                    # self.event.value is the EventTypes enum's class. For
                    # every non-Control channel (the only ones reaching this
                    # code path — ControlHandler overrides handle_message)
                    # the result is a BaseEvent subclass. The cast narrows
                    # the Union to satisfy the typed list.
                    event = cast(BaseEvent, self.event.value(**data))
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

            return events

        except Exception as e:
            logger.warning("Skipped invalid event on %s channel: %s", channel_name, e)
            raise MessageProcessingError("Skipped invalid event", e) from e


class ControlHandler(EventHandler):
    def __init__(self, reconnect_signal: Optional[ReconnectSignal] = None) -> None:
        super().__init__(channel=Channels.Control)
        self.reconnect_signal = reconnect_signal
        self.was_authorized = False  # Track if we've been authorized before
        # Handshake ack events — awaited by DXLinkManager.open() to enforce
        # protocol ordering: SETUP -> AUTH_STATE:AUTHORIZED -> CHANNEL_OPENED per channel.
        self.setup_done: asyncio.Event = asyncio.Event()
        self.authorized: asyncio.Event = asyncio.Event()
        self.channel_opened: Dict[int, asyncio.Event] = {
            channel.value: asyncio.Event()
            for channel in Channels
            if channel != Channels.Control
        }
        self.control_handlers: Dict[str, Callable[[Message], Awaitable[None]]] = {
            "SETUP": self.handle_setup,
            "AUTH_STATE": self.handle_auth_state,
            "CHANNEL_OPENED": self.handle_channel_opened,
            "FEED_CONFIG": self.handle_feed_config,
            "KEEPALIVE": self.handle_keepalive,
            "ERROR": self.handle_error,
            "CONNECTION_DROPPED": self.handle_connection_dropped,
        }

    async def handle_batch(self, replies: List[dict]) -> None:
        """Control messages are commands, not data events — handle each in
        order, per message, exactly as the serial loop did."""
        for reply in replies:
            await self.handle_message(self.make_message(reply))

    async def handle_message(self, message: Message) -> None:
        if self.control_handlers.get(message.type):
            await self.control_handlers[message.type](message)
        else:
            logger.warning("No handler found for message type: %s", message.type)

    async def handle_setup(self, message: Message) -> None:
        logger.info("%s", message.type)
        self.setup_done.set()

    async def handle_auth_state(self, message: Message) -> None:
        state = message.headers.get("state", "UNKNOWN")
        if state == "AUTHORIZED":
            self.was_authorized = True
            self.authorized.set()
            logger.info("%s:%s", message.type, state)
        elif state == "UNAUTHORIZED":
            # Only trigger reconnect if we were previously authorized
            # Initial UNAUTHORIZED during handshake is expected
            self.authorized.clear()
            if self.was_authorized:
                logger.error("DXLink AUTH_STATE: UNAUTHORIZED - triggering reconnect")
                if self.reconnect_signal:
                    self.reconnect_signal.trigger(ReconnectReason.AUTH_EXPIRED)
            else:
                logger.debug("AUTH_STATE: UNAUTHORIZED (initial handshake, expected)")
        else:
            logger.info("%s:%s", message.type, state)

    async def handle_channel_opened(self, message: Message) -> None:
        logger.info("%s:%s", message.type, message.channel)
        event = self.channel_opened.get(message.channel)
        if event is not None:
            event.set()

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
            if self.reconnect_signal:
                self.reconnect_signal.trigger(ReconnectReason.TIMEOUT)
        elif error_type == "UNAUTHORIZED":
            logger.error("DXLink %s: %s - triggering reconnect", error_type, error_msg)
            if self.reconnect_signal:
                self.reconnect_signal.trigger(ReconnectReason.AUTH_EXPIRED)
        elif error_type == "UNSUPPORTED_PROTOCOL":
            logger.critical("DXLink UNSUPPORTED_PROTOCOL: %s - fatal error", error_msg)
        elif error_type in ("INVALID_MESSAGE", "BAD_ACTION"):
            # dxFeed emits "subscription size for event type 'X' is too big"
            # for both genuine cap violations AND duplicate re-subscribes
            # against an already-active sub. Neither is a connection failure;
            # the existing subscription (if any) keeps delivering data. We
            # demote to debug — the dedup-via-Redis path is unreliable enough
            # that re-subscribing as fail-safe is intentional.
            if "subscription size" in error_msg.lower():
                logger.debug(
                    "DXLink candle re-subscribe ignored by server "
                    "(duplicate or over-cap; existing data flow unaffected)"
                )
                return
            logger.error("DXLink %s: %s - triggering reconnect", error_type, error_msg)
            if self.reconnect_signal:
                self.reconnect_signal.trigger(ReconnectReason.PROTOCOL_ERROR)
        else:
            logger.warning("DXLink %s: %s", error_type, error_msg)

    async def handle_connection_dropped(self, message: Message) -> None:
        reason_value = message.headers.get(
            "reason", ReconnectReason.CONNECTION_DROPPED.value
        )
        try:
            reason = ReconnectReason(reason_value)
        except ValueError:
            reason = ReconnectReason.CONNECTION_DROPPED
        logger.error("CONNECTION_DROPPED: %s - triggering reconnect", reason.value)
        if self.reconnect_signal:
            self.reconnect_signal.trigger(reason)
