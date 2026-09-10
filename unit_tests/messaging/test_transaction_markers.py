"""dxFeed transaction bookkeeping is dropped once, at ingestion.

dxFeed wraps a candle correction in a transaction: a TX_PENDING copy of the
forming bar, then a virtual REMOVE_EVENT at index Long.MAX_VALUE (a 2038
timestamp, no prices). The placeholder is not a bar; consumers that detect a
new bar by a newer timestamp would seal the forming bar early on it. It never
leaves the candle handler. Records that also end a snapshot are kept for the
snapshot tracker.
"""

import json
from pathlib import Path
from typing import Any

from tastytrade.config.configurations import CHANNEL_SPECS
from tastytrade.config.enumerations import Channels
from tastytrade.messaging.handlers import EventHandler, is_transaction_marker
from tastytrade.messaging.models.events import CandleEvent
from tastytrade.messaging.processors.default import BaseEventProcessor

FIELDS = CHANNEL_SPECS[Channels.Candle].fields
FIXTURE = (
    Path(__file__).parent.parent
    / "research"
    / "fixtures"
    / "spx5m_tap_2026-09-10_1040_1050.jsonl"
)
SENTINEL_TIME = "2038-01-19T03:14:08.023000Z"


def candle_reply(*records: dict[str, Any]) -> dict[str, Any]:
    """FEED_DATA shape: the event type name, then one flat list of field values."""
    flat = [r.get(f) for r in records for f in FIELDS]
    return {
        "type": "FEED_DATA",
        "channel": Channels.Candle.value,
        "data": ["Candle", flat],
    }


def record(
    time: str, flags: int, close: float | None, count: int = 1
) -> dict[str, Any]:
    return {
        "eventSymbol": "SPX{=5m}",
        "time": time,
        "eventFlags": flags,
        "index": 1,
        "sequence": 0,
        "count": count,
        "close": close,
    }


def handler() -> EventHandler:
    h = EventHandler(channel=Channels.Candle, processor=BaseEventProcessor())
    h.subscription_store = None
    return h


def test_predicate() -> None:
    def ev(flags: int, close: float | None) -> CandleEvent:
        return CandleEvent(
            eventSymbol="SPX{=5m}", time=SENTINEL_TIME, eventFlags=flags, close=close
        )

    assert is_transaction_marker(ev(2, None))  # REMOVE_EVENT placeholder
    assert not is_transaction_marker(
        ev(1, 7601.95)
    )  # TX_PENDING copy is a real bar state
    assert not is_transaction_marker(ev(0, 7600.73))
    assert not is_transaction_marker(
        ev(2 | 8, None)
    )  # empty-snapshot end feeds the tracker
    assert not is_transaction_marker(ev(2 | 16, None))


def test_placeholder_never_leaves_the_candle_handler() -> None:
    h = handler()
    events = h.parse_events(
        h.make_message(
            candle_reply(
                record("2026-09-10T14:45:00Z", 0, 7601.47),
                record("2026-09-10T14:45:00Z", 1, 7601.95),
                record(SENTINEL_TIME, 2, None, count=0),
                record("2026-09-10T14:45:00Z", 0, 7600.73),
                record(SENTINEL_TIME, 2 | 8, None, count=0),
            )
        )
    )
    assert [(e.eventFlags, e.close) for e in events] == [  # type: ignore[attr-defined]
        (0, 7601.47),
        (1, 7601.95),
        (0, 7600.73),
        (10, None),
    ]


def test_recorded_feed_2026_09_10_1045_bar() -> None:
    """The recorded feed around the 10:45 ET bar: the handler drops exactly the
    one placeholder and passes every priced record through."""
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    for r in rows:
        r.pop("wall")
    h = handler()
    events = h.parse_events(h.make_message(candle_reply(*rows)))
    assert len(events) == len(rows) - 1
    assert all(e.time.year < 2030 for e in events)  # type: ignore[attr-defined]
    assert all(e.close is not None for e in events)  # type: ignore[attr-defined]
