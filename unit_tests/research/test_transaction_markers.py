"""The Kalman filter updates exactly once per bar.

The filter is recursive, so a bar presented twice (a warmup/live overlap on a
restart, or a replay that repeats a bar) would be a fake extra step in the
price path. The bar-close gate itself relies on the candle pipeline dropping
dxFeed transaction bookkeeping at ingestion (see
unit_tests/messaging/test_transaction_markers.py).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tastytrade.messaging.handlers import is_transaction_marker
from tastytrade.messaging.models.events import CandleEvent

from research.tt156_zero_dte_butterfly.signals import HullSignalEngine

T0 = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)
SYM5 = "SPX{=5m}"
FIXTURE = Path(__file__).parent / "fixtures" / "spx5m_tap_2026-09-10_1040_1050.jsonl"


def bar(minute: int, close: float) -> CandleEvent:
    return CandleEvent(
        eventSymbol=SYM5, time=T0 + timedelta(minutes=minute), close=close
    )


def kalman_engine() -> HullSignalEngine:
    eng = HullSignalEngine(confirm_on_close=True)
    for i in range(6):
        eng.ingest_sealed(bar(-30 + 5 * i, 7580.0 + 2 * i), emit=False)
    return eng


def test_same_bar_updates_kalman_once() -> None:
    eng = kalman_engine()
    eng.ingest_sealed(bar(0, 7601.95), emit=True)
    velocity_after_first = eng.kalman_x[1] if eng.kalman_x else None
    eng.ingest_sealed(bar(0, 7600.73), emit=True)
    assert eng.kalman_x is not None
    assert eng.kalman_x[1] == velocity_after_first


def test_naive_warmup_then_aware_live_bar() -> None:
    """InfluxDB warmup rows are naive, live events aware; the guard must not raise."""
    eng = HullSignalEngine(confirm_on_close=True)
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
    """The recorded feed around the 10:45 ET bar, after the ingestion drop,
    reaches the Kalman exactly once, on the bar's real close."""
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
        event = CandleEvent(**row)
        if not is_transaction_marker(event):
            eng.on_candle(event)

    bar_1045 = datetime(2026, 9, 10, 14, 45, tzinfo=timezone.utc)
    assert [s for s in sealed if s[0] == bar_1045] == [(bar_1045, 7600.73)]
