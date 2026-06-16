"""Bar-close gate: the engine must only see sealed candles (TT-156).

Precludes trades taken before a full Hull candle establishes the signal —
the forming bar is buffered and forwarded only once a newer bar opens.
"""

from datetime import datetime, timedelta, timezone

from tastytrade.messaging.models.events import CandleEvent

from research.tt156_zero_dte_butterfly.signals import LiveSignalEngine

T0 = datetime(2026, 6, 16, 14, 30, tzinfo=timezone.utc)
SYM = "SPX{=m}"


def candle(minute: int, close: float) -> CandleEvent:
    return CandleEvent(
        eventSymbol=SYM, time=T0 + timedelta(minutes=minute), close=close
    )


class FakeEngine:
    def __init__(self) -> None:
        self.seen: list[tuple[datetime, float | None]] = []

    def on_candle_event(self, event: CandleEvent) -> None:
        self.seen.append((event.time, event.close))


def make_engine(confirm: bool) -> tuple[LiveSignalEngine, FakeEngine]:
    eng = LiveSignalEngine(confirm_on_close=confirm)
    fake = FakeEngine()
    eng.engine = fake  # type: ignore[assignment]
    return eng, fake


def test_intra_candle_updates_are_not_forwarded() -> None:
    eng, fake = make_engine(confirm=True)
    # bar 0 ticks three times (intra-candle), then bar 1 opens, then bar 2.
    eng.on_candle(candle(0, 7500.0))
    eng.on_candle(candle(0, 7505.0))
    eng.on_candle(candle(0, 7498.0))  # bar 0 final close
    eng.on_candle(candle(1, 7510.0))  # opening bar 1 seals bar 0
    eng.on_candle(candle(2, 7520.0))  # opening bar 2 seals bar 1

    # Only sealed bars reach the engine, carrying each bar's final close.
    assert fake.seen == [
        (T0 + timedelta(minutes=0), 7498.0),
        (T0 + timedelta(minutes=1), 7510.0),
    ]


def test_forming_bar_is_held_until_it_seals() -> None:
    eng, fake = make_engine(confirm=True)
    eng.on_candle(candle(0, 7500.0))
    assert fake.seen == []  # first bar is still forming — nothing forwarded
    eng.on_candle(candle(1, 7510.0))
    assert [c[0] for c in fake.seen] == [T0]  # bar 0 sealed when bar 1 opened


def test_disabled_forwards_every_event() -> None:
    eng, fake = make_engine(confirm=False)
    eng.on_candle(candle(0, 7500.0))
    eng.on_candle(candle(0, 7505.0))
    eng.on_candle(candle(1, 7510.0))
    assert len(fake.seen) == 3  # legacy intrabar behavior preserved


def test_spot_tracking_stays_live() -> None:
    eng, _ = make_engine(confirm=True)
    eng.on_candle(candle(0, 7500.0))
    eng.on_candle(candle(0, 7505.0))  # intra-candle update
    # spot follows the latest tick even though the bar hasn't sealed
    assert eng.latest_spot == 7505.0
