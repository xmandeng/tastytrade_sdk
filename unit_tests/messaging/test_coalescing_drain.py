"""Coalescing + pipelined intake drain.

The listener empties whatever is already queued (bounded by DRAIN_SLICE),
dispatches the batch once, and the Redis processor sends the batch's
commands in one pipelined round-trip. An empty queue yields a batch of one
— per-event behavior unchanged on a current channel.
"""

import asyncio
from typing import Any

import pytest

from tastytrade.config.enumerations import Channels
from tastytrade.messaging.handlers import (
    DRAIN_SLICE,
    STATUS_STAMP_SECONDS,
    EventHandler,
)
from tastytrade.messaging.processors.default import BaseEventProcessor
from tastytrade.messaging.processors.redis import RedisEventProcessor


def quote_reply(symbol: str, bid: float = 1.0, ask: float = 2.0) -> dict:
    return {
        "type": "FEED_DATA",
        "channel": Channels.Quote.value,
        "data": [[symbol, bid, ask, 100.0, 200.0]],
    }


class RecordingProcessor(BaseEventProcessor):
    """Counts batch calls and records event order via the default loop."""

    name = "recording"

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[int] = []
        self.symbols: list[str] = []

    def process_events(self, events) -> None:  # type: ignore[override]
        self.batches.append(len(events))
        for event in events:
            self.symbols.append(event.eventSymbol)


class FakePipeline:
    def __init__(self, commands: list[tuple]) -> None:
        self.commands = commands
        self.executes = 0

    def publish(self, channel: str, message: str) -> None:
        self.commands.append(("publish", channel))

    def hset(self, key: str, field: str, value: str) -> None:
        self.commands.append(("hset", key, field))

    async def execute(self) -> list:
        self.commands.append(("execute",))
        return []


class FakeRedis:
    def __init__(self) -> None:
        self.commands: list[tuple] = []
        self.execute_count = 0

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        assert transaction is False  # order-preserving, non-transactional
        return FakePipeline(self.commands)


class FakeStore:
    def __init__(self) -> None:
        self.stamps: list[str] = []

    async def update_subscription_status(self, symbol: str, data: dict) -> None:
        self.stamps.append(symbol)


def handler_with(processor: BaseEventProcessor, store: Any = None) -> EventHandler:
    h = EventHandler(channel=Channels.Quote, processor=processor)
    h.subscription_store = store
    return h


class TestCoalescing:
    @pytest.mark.asyncio
    async def test_batch_of_one_on_empty_queue(self) -> None:
        rec = RecordingProcessor()
        h = handler_with(rec)
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(quote_reply("SPY"))

        task = asyncio.create_task(h.queue_listener(queue))
        await queue.join()
        h.stop_listener.set()
        task.cancel()

        assert rec.batches == [1]
        assert rec.symbols == ["SPY"]

    @pytest.mark.asyncio
    async def test_backlog_coalesces_into_one_dispatch(self) -> None:
        rec = RecordingProcessor()
        h = handler_with(rec)
        queue: asyncio.Queue = asyncio.Queue()
        for i in range(7):
            await queue.put(quote_reply(f"S{i}"))

        task = asyncio.create_task(h.queue_listener(queue))
        await queue.join()
        h.stop_listener.set()
        task.cancel()

        assert rec.batches == [7]
        assert rec.symbols == [f"S{i}" for i in range(7)]  # order preserved

    @pytest.mark.asyncio
    async def test_slice_cap_bounds_a_deep_backlog(self) -> None:
        rec = RecordingProcessor()
        h = handler_with(rec)
        queue: asyncio.Queue = asyncio.Queue()
        for i in range(DRAIN_SLICE + 3):
            await queue.put(quote_reply(f"S{i}"))

        task = asyncio.create_task(h.queue_listener(queue))
        await queue.join()
        h.stop_listener.set()
        task.cancel()

        assert rec.batches == [DRAIN_SLICE, 3]
        assert len(rec.symbols) == DRAIN_SLICE + 3  # nothing lost

    @pytest.mark.asyncio
    async def test_bad_reply_skipped_rest_of_slice_survives(self) -> None:
        rec = RecordingProcessor()
        h = handler_with(rec)
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(quote_reply("GOOD1"))
        await queue.put(quote_reply("BAD", ask=None))  # type: ignore[arg-type]
        await queue.put(quote_reply("GOOD2"))

        task = asyncio.create_task(h.queue_listener(queue))
        await queue.join()
        h.stop_listener.set()
        task.cancel()

        assert rec.symbols == ["GOOD1", "GOOD2"]
        assert h.metrics.error_count >= 1


class TestPipelinedRedis:
    @pytest.mark.asyncio
    async def test_batch_is_one_pipeline_execute(self) -> None:
        p = RedisEventProcessor.__new__(RedisEventProcessor)
        p.redis = FakeRedis()  # type: ignore[assignment]
        p.last_lag_warning = 0.0
        h = handler_with(BaseEventProcessor())
        events = []
        for i in range(3):
            events.extend(h.parse_events(h.make_message(quote_reply(f"S{i}"))))

        await p.process_events(events)

        cmds = p.redis.commands  # type: ignore[attr-defined]
        assert cmds.count(("execute",)) == 1
        # publish before hset for each event, events in order
        kinds = [c[0] for c in cmds[:-1]]
        assert kinds == ["publish", "hset"] * 3

    @pytest.mark.asyncio
    async def test_process_event_delegates_to_batch(self) -> None:
        p = RedisEventProcessor.__new__(RedisEventProcessor)
        p.redis = FakeRedis()  # type: ignore[assignment]
        p.last_lag_warning = 0.0
        h = handler_with(BaseEventProcessor())
        (event,) = h.parse_events(h.make_message(quote_reply("SPY")))

        await p.process_event(event)

        assert p.redis.commands[-1] == ("execute",)  # type: ignore[attr-defined]


class ProtocolOnlyProcessor:
    """Implements only the EventProcessor protocol — no BaseEventProcessor,
    no process_events (the CandleSnapshotTracker shape)."""

    name = "protocol_only"

    def __init__(self) -> None:
        self.symbols: list[str] = []

    def process_event(self, event) -> None:
        self.symbols.append(event.eventSymbol)

    def close(self) -> None:
        pass


class TestProtocolOnlyProcessor:
    @pytest.mark.asyncio
    async def test_batch_feeds_process_event_per_event(self) -> None:
        rec = RecordingProcessor()
        h = handler_with(rec)
        proto = ProtocolOnlyProcessor()
        h.add_processor(proto)  # type: ignore[arg-type]
        events = []
        for i in range(3):
            events.extend(h.parse_events(h.make_message(quote_reply(f"S{i}"))))

        await h.dispatch_batch(events)

        assert proto.symbols == ["S0", "S1", "S2"]
        assert rec.batches == [3]


class TestStatusThrottle:
    @pytest.mark.asyncio
    async def test_symbol_stamped_once_per_batch(self) -> None:
        store = FakeStore()
        h = handler_with(RecordingProcessor(), store)
        events = []
        for _ in range(5):
            events.extend(h.parse_events(h.make_message(quote_reply("SPY"))))

        await h.touch_subscriptions(events)

        assert store.stamps == ["SPY"]

    @pytest.mark.asyncio
    async def test_recent_stamp_skipped_then_expires(self) -> None:
        store = FakeStore()
        h = handler_with(RecordingProcessor(), store)
        (event,) = h.parse_events(h.make_message(quote_reply("SPY")))

        await h.touch_subscriptions([event])
        await h.touch_subscriptions([event])  # within the window — skipped
        assert store.stamps == ["SPY"]

        h.last_status_stamp["SPY"] -= STATUS_STAMP_SECONDS + 0.01
        await h.touch_subscriptions([event])
        assert store.stamps == ["SPY", "SPY"]
