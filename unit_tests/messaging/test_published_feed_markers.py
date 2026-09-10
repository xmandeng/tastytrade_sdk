"""Published candle feeds are cleaned of dxFeed transaction bookkeeping.

dxFeed wraps a candle correction in a transaction: a TX_PENDING copy of the
forming bar, then a virtual REMOVE_EVENT at index Long.MAX_VALUE (a 2038
timestamp, no prices). The placeholder is not a bar; a subscriber that detects
a new bar by a newer timestamp would seal the forming bar early on it. The
Redis publisher drops it once, so no subscriber carries the check. Records
that also end a snapshot are kept.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tastytrade.messaging.models.events import CandleEvent
from tastytrade.messaging.processors.redis import (
    RedisEventProcessor,
    is_transaction_marker,
)

FIXTURE = (
    Path(__file__).parent.parent
    / "research"
    / "fixtures"
    / "spx5m_tap_2026-09-10_1040_1050.jsonl"
)
SENTINEL_TIME = "2038-01-19T03:14:08.023000Z"


class FakePipeline:
    def __init__(self, published: list[str]) -> None:
        self.published = published

    def publish(self, channel: str, message: str) -> None:
        self.published.append(message)

    def hset(self, key: str, field: str, value: str) -> None:
        return None

    async def execute(self) -> list:
        return []


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[str] = []

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        return FakePipeline(self.published)


def processor() -> RedisEventProcessor:
    p = RedisEventProcessor.__new__(RedisEventProcessor)
    p.redis = FakeRedis()  # type: ignore[assignment]
    p.last_lag_warning = 0.0
    return p


def candle(time: str, flags: int, close: float | None) -> CandleEvent:
    return CandleEvent(eventSymbol="SPX{=5m}", time=time, eventFlags=flags, close=close)


def test_predicate() -> None:
    assert is_transaction_marker(
        candle(SENTINEL_TIME, 2, None)
    )  # REMOVE_EVENT placeholder
    assert not is_transaction_marker(
        candle(SENTINEL_TIME, 1, 7601.95)
    )  # TX_PENDING copy is a bar
    assert not is_transaction_marker(candle(SENTINEL_TIME, 0, 7600.73))
    assert not is_transaction_marker(
        candle(SENTINEL_TIME, 2 | 8, None)
    )  # empty-snapshot end
    assert not is_transaction_marker(candle(SENTINEL_TIME, 2 | 16, None))


@pytest.mark.asyncio
async def test_placeholder_is_not_published() -> None:
    p = processor()
    await p.process_events(
        [
            candle("2026-09-10T14:45:00Z", 0, 7601.47),
            candle("2026-09-10T14:45:00Z", 1, 7601.95),
            candle(SENTINEL_TIME, 2, None),
            candle("2026-09-10T14:45:00Z", 0, 7600.73),
            candle(SENTINEL_TIME, 2 | 8, None),
        ]
    )
    published: list[dict[str, Any]] = [json.loads(m) for m in p.redis.published]  # type: ignore[attr-defined]
    assert [(m["eventFlags"], m["close"]) for m in published] == [
        (0, 7601.47),
        (1, 7601.95),
        (0, 7600.73),
        (10, None),
    ]


@pytest.mark.asyncio
async def test_recorded_feed_2026_09_10_1045_bar() -> None:
    """The recorded feed around the 10:45 ET bar: exactly the one placeholder
    is withheld and every priced record is published."""
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    for r in rows:
        r.pop("wall")
    p = processor()
    await p.process_events([CandleEvent(**r) for r in rows])
    published = p.redis.published  # type: ignore[attr-defined]
    assert len(published) == len(rows) - 1
    assert all(json.loads(m)["close"] is not None for m in published)
