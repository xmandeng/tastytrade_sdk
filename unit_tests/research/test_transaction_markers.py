"""dxFeed transaction records never act as bars, and the Kalman updates once per bar.

dxFeed wraps a candle correction in a transaction: a TX_PENDING copy of the
forming bar, then a virtual REMOVE_EVENT at index Long.MAX_VALUE (a 2038
timestamp, no prices). The engines detect a new bar by a newer timestamp, so
the placeholder would seal the forming bar early and the real close would seal
it again. The check lives in the engines, the consumers that need it. The
Kalman's own once-per-bar guard covers a bar presented twice by any other route.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tastytrade.messaging.models.events import CandleEvent

from research.tt156_zero_dte_butterfly.signals import (
    LiveSignalEngine,
    SealedBarSignalEngine,
    is_transaction_marker,
)

T0 = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)
SYM5 = "SPX{=5m}"
SENTINEL_TIME = datetime(2038, 1, 19, 3, 14, 8, 23000, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "spx5m_tap_2026-09-10_1040_1050.jsonl"


def bar(minute: int, close: float, flags: int = 0) -> CandleEvent:
    return CandleEvent(
        eventSymbol=SYM5,
        time=T0 + timedelta(minutes=minute),
        close=close,
        eventFlags=flags,
    )


def placeholder() -> CandleEvent:
    return CandleEvent(eventSymbol=SYM5, time=SENTINEL_TIME, eventFlags=2, count=0)


def kalman_engine() -> SealedBarSignalEngine:
    eng = SealedBarSignalEngine(confirm_on_close=True)
    for i in range(6):
        eng.ingest_sealed(bar(-30 + 5 * i, 7580.0 + 2 * i), emit=False)
    return eng


def test_marker_predicate() -> None:
    assert is_transaction_marker(placeholder())
    assert is_transaction_marker(CandleEvent(eventSymbol=SYM5, time=T0))  # no close
    assert not is_transaction_marker(
        bar(0, 7601.95, flags=1)
    )  # TX_PENDING copy is a bar
    assert not is_transaction_marker(bar(0, 7600.0))
    assert not is_transaction_marker(bar(0, 7600.0, flags=4))


class FakeEngine:
    def __init__(self) -> None:
        self.seen: list[tuple[datetime, float | None]] = []

    def on_candle_event(self, event: CandleEvent) -> None:
        self.seen.append((event.time, event.close))


def test_live_gate_ignores_placeholder() -> None:
    eng = LiveSignalEngine(confirm_on_close=True)
    fake = FakeEngine()
    eng.engine = fake  # type: ignore[assignment]
    eng.on_candle(bar(0, 7600.0))
    eng.on_candle(bar(0, 7601.5, flags=1))
    eng.on_candle(placeholder())
    assert fake.seen == []  # bar 0 is still forming
    eng.on_candle(bar(0, 7599.0))
    eng.on_candle(bar(5, 7602.0))
    assert fake.seen == [(T0, 7599.0)]  # sealed once, on its real close


def test_placeholder_does_not_seal_forming_bar() -> None:
    eng = kalman_engine()
    before = eng.kalman_last_time
    eng.on_candle(bar(0, 7592.0))
    eng.on_candle(bar(0, 7593.0, flags=1))
    eng.on_candle(placeholder())
    assert eng.kalman_last_time == before
    eng.on_candle(bar(0, 7590.0))
    eng.on_candle(bar(5, 7591.0))
    assert eng.kalman_last_time == T0


def test_same_bar_updates_kalman_once() -> None:
    eng = kalman_engine()
    eng.ingest_sealed(bar(0, 7601.95), emit=True)
    velocity_after_first = eng.kalman_x[1] if eng.kalman_x else None
    eng.ingest_sealed(bar(0, 7600.73), emit=True)
    assert eng.kalman_x is not None
    assert eng.kalman_x[1] == velocity_after_first


def test_naive_warmup_then_aware_live_bar() -> None:
    """InfluxDB warmup rows are naive, live events aware; the guard must not raise."""
    eng = SealedBarSignalEngine(confirm_on_close=True)
    for i in range(6):
        eng.ingest_sealed(
            CandleEvent(
                eventSymbol=SYM5,
                time=(T0 + timedelta(minutes=-30 + 5 * i)).replace(tzinfo=None),
                close=7580.0 + 2 * i,
            ),
            emit=False,
        )
    eng.ingest_sealed(bar(0, 7592.0), emit=True)
    assert eng.kalman_last_time == T0


def test_recorded_feed_seals_the_1045_bar_once() -> None:
    """The recorded raw feed around the 10:45 ET bar, with its TX_PENDING copy
    and placeholder, reaches the Kalman exactly once, on the bar's real close."""
    eng = kalman_engine()
    sealed: list[tuple[datetime, float | None]] = []
    original = eng.ingest_sealed

    def spy(event: CandleEvent, emit: bool) -> None:
        sealed.append((event.time, event.close))
        original(event, emit)

    eng.ingest_sealed = spy  # type: ignore[method-assign]
    for line in FIXTURE.read_text().splitlines():
        row = json.loads(line)
        row.pop("wall")
        eng.on_candle(CandleEvent(**row))

    bar_1045 = datetime(2026, 9, 10, 14, 45, tzinfo=timezone.utc)
    assert [s for s in sealed if s[0] == bar_1045] == [(bar_1045, 7600.73)]
    assert all(s[0] < SENTINEL_TIME - timedelta(days=365) for s in sealed)
