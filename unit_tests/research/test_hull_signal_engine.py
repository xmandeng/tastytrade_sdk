"""HullSignalEngine — the Basics v2 forward-test rule (2026-08-27).

Direction follows the 5m hull, full stop: OPEN on a sealed-bar color flip
inside 10:00-14:00 ET, CLOSE for the old direction on every flip, MACD
nowhere.
"""

from datetime import datetime, timedelta, timezone

from tastytrade.messaging.models.events import CandleEvent

from research.tt156_zero_dte_butterfly.signals import HullSignalEngine


def bar(ts: datetime, close: float) -> CandleEvent:
    return CandleEvent(
        eventSymbol="SPX{=5m}",
        time=ts,
        open=close,
        high=close,
        low=close,
        close=close,
    )


def seeded_engine(start: datetime, closes: list[float]) -> HullSignalEngine:
    """Engine with a declining warmup ramp then the given closes fed sealed."""
    eng = HullSignalEngine(confirm_on_close=False)
    t = start - timedelta(minutes=5 * 60)
    for i in range(40):  # long down ramp so hull starts firmly Down
        eng.ingest_sealed(bar(t, 7700.0 - i * 2), emit=False)
        t += timedelta(minutes=5)
    eng.engine.signals.clear()
    eng.capture.drain()
    t = start
    for c in closes:
        eng.on_candle(bar(t, c))
        t += timedelta(minutes=5)
    return eng


def rally(n: int = 25) -> list[float]:
    return [7622.0 + i * 4 for i in range(n)]


class TestHullSignalEngine:
    def test_flip_in_window_emits_close_and_open(self) -> None:
        start = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)  # 11:00 ET
        eng = seeded_engine(start, rally())
        sigs = [s for s in eng.capture.drain() if s.engine == "hull_only"]
        opens = [s for s in sigs if s.signal_type == "OPEN"]
        closes = [s for s in sigs if s.signal_type == "CLOSE"]
        assert len(opens) == 1
        assert opens[0].direction == "BULLISH"
        assert opens[0].trigger == "hull_flip"
        assert opens[0].engine == "hull_only"
        assert closes and closes[0].direction == "BEARISH"
        assert closes[0].trigger == "hull"

    def test_flip_outside_window_emits_close_only(self) -> None:
        start = datetime(2026, 8, 27, 19, 30, tzinfo=timezone.utc)  # 15:30 ET
        eng = seeded_engine(start, rally())
        sigs = eng.capture.drain()
        assert all(s.signal_type == "CLOSE" for s in sigs)
        assert sigs, "exit signals must still fire outside the entry window"

    def test_no_flip_no_signal(self) -> None:
        start = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
        eng = seeded_engine(start, [7620.0 - i * 3 for i in range(10)])
        assert eng.capture.drain() == []
        assert eng.hull_color == "Down"

    def test_confirm_on_close_buffers_forming_bar(self) -> None:
        start = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
        eng = HullSignalEngine(confirm_on_close=True)
        t = start - timedelta(minutes=5 * 40)
        for i in range(40):
            eng.ingest_sealed(bar(t, 7700.0 - i * 2), emit=False)
            t += timedelta(minutes=5)
        before = eng.candles.height
        eng.on_candle(bar(start, 7650.0))  # forming — buffered, not ingested
        assert eng.candles.height == before
        eng.on_candle(bar(start + timedelta(minutes=5), 7655.0))  # seals prior
        assert eng.candles.height == before + 1

    def test_gate_context_is_none(self) -> None:
        assert HullSignalEngine().gate_context() is None

    def test_state_summary_reports_hull_only(self) -> None:
        start = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
        eng = seeded_engine(start, rally())
        summary = eng.state_summary()
        assert summary["SPX{=5m}"]["hull_direction"] == "Up"
        assert summary["SPX{=5m}"]["macd_position"] is None

    def test_spot_tracking_from_1m_channel(self) -> None:
        eng = HullSignalEngine()
        ts = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
        eng.on_candle(
            CandleEvent(
                eventSymbol="SPX{=m}", time=ts, open=1, high=1, low=1, close=7711.5
            )
        )
        assert eng.latest_spot == 7711.5
        assert eng.latest_spot_time == ts
