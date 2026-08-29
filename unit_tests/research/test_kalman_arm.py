"""Kalman tangent tracked arms (user-approved 2026-08-28): constant-velocity
Kalman on sealed 5m closes, q/r=0.025; velocity sign flips emit a parallel
signal family (engine="kalman") routed only to signal_source="kalman" arms."""

from datetime import datetime, timedelta, timezone
from typing import cast

from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.messaging.models.events import CandleEvent

from research.tt156_zero_dte_butterfly.config import VariantConfig, default_variants
from research.tt156_zero_dte_butterfly.signals import HullSignalEngine
from research.tt156_zero_dte_butterfly.simulator import (
    ButterflySimulator,
    signal_matches,
)

TS = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)  # 11:00 ET


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
    """Engine warmed on a down ramp (velocity firmly negative), then live."""
    eng = HullSignalEngine(confirm_on_close=False)
    t = start - timedelta(minutes=5 * 60)
    for i in range(40):
        eng.ingest_sealed(bar(t, 7700.0 - i * 2), emit=False)
        t += timedelta(minutes=5)
    eng.engine.signals.clear()
    eng.capture.drain()
    t = start
    for c in closes:
        eng.on_candle(bar(t, c))
        t += timedelta(minutes=5)
    return eng


def kalman_sigs(eng: HullSignalEngine) -> list[TradeSignal]:
    return [s for s in eng.capture.drain() if s.engine == "kalman"]


class FakeHullSignal:
    eventSymbol = "SPX{=5m}"
    signal_type = "OPEN"
    direction = "BULLISH"
    trigger = "hull_flip"
    engine = "hull_only"


class FakeKalmanSignal:
    eventSymbol = "SPX{=5m}"
    signal_type = "OPEN"
    direction = "BULLISH"
    trigger = "kalman_flip"
    engine = "kalman"


class RigSig:
    """Replay-rig stub without an engine attribute — hull family."""

    eventSymbol = "SPX{=5m}"
    signal_type = "OPEN"
    direction = "BULLISH"
    trigger = "hull_flip"


def quotes_for(spot: float, base: float = 4.0) -> dict:
    """Moneyness-skewed extrinsic so ATM verticals collect a positive credit."""
    q = {}
    start = (int(spot) - 200) // 5 * 5
    for k in range(start, start + 405, 5):
        extrinsic = max(0.5, base - 0.02 * abs(k - spot))
        for cp in ("C", "P"):
            intrinsic = max(spot - k, 0.0) if cp == "C" else max(k - spot, 0.0)
            mid_val = intrinsic + extrinsic
            q[(float(k), cp)] = {"bid": mid_val - 0.2, "ask": mid_val + 0.2}
    return q


class TestVariantGrid:
    def test_default_grid_includes_kalman_arms(self) -> None:
        by_name = {v.name: v for v in default_variants()}
        assert by_name["w25_5m_m0_kal"].signal_source == "kalman"
        assert by_name["w25_5m_m0_kal_ef5"].signal_source == "kalman"
        assert by_name["w25_5m_m0_kal_ef5"].early_fly_adverse_pts == 5.0
        assert by_name["w25_5m_m0"].signal_source == "hull"


class TestKalmanSignals:
    def test_flip_in_window_emits_close_and_open(self) -> None:
        eng = seeded_engine(TS, [7622.0 + i * 4 for i in range(10)])
        sigs = kalman_sigs(eng)
        opens = [s for s in sigs if s.signal_type == "OPEN"]
        closes = [s for s in sigs if s.signal_type == "CLOSE"]
        assert len(opens) == 1
        assert opens[0].direction == "BULLISH"
        assert opens[0].trigger == "kalman_flip"
        assert closes and closes[0].direction == "BEARISH"
        assert closes[0].trigger == "kalman"

    def test_flip_outside_window_emits_close_only(self) -> None:
        late = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)  # 15:30 ET
        eng = seeded_engine(late, [7622.0 + i * 4 for i in range(10)])
        sigs = kalman_sigs(eng)
        assert sigs, "exit signals must still fire outside the entry window"
        assert all(s.signal_type == "CLOSE" for s in sigs)

    def test_no_flip_no_kalman_signal(self) -> None:
        eng = seeded_engine(TS, [7620.0 - i * 3 for i in range(10)])
        assert kalman_sigs(eng) == []
        assert eng.kalman_sign == "Down"

    def test_kalman_flips_before_hull(self) -> None:
        """The point of the arm: on a sharp reversal the velocity sign flips
        on an earlier sealed bar than the hull color."""
        eng = HullSignalEngine(confirm_on_close=False)
        t = TS - timedelta(minutes=5 * 60)
        for i in range(40):
            eng.ingest_sealed(bar(t, 7700.0 - i * 2), emit=False)
            t += timedelta(minutes=5)
        eng.capture.drain()
        kal_at = hull_at = None
        t = TS
        for i in range(15):
            eng.on_candle(bar(t, 7622.0 + i * 4))
            for s in eng.capture.drain():
                if s.signal_type != "CLOSE":  # exits fire on every flip
                    continue
                if s.engine == "kalman" and kal_at is None:
                    kal_at = i
                if s.engine == "hull_only" and hull_at is None:
                    hull_at = i
            t += timedelta(minutes=5)
        assert kal_at is not None and hull_at is not None
        assert kal_at <= hull_at


class TestRouting:
    def test_signal_matches_is_disjoint(self) -> None:
        hull_arm = VariantConfig(
            name="w25_5m_m0", width=25.0, signal_interval="5m", completion_margin=0.0
        )
        kal_arm = VariantConfig(
            name="w25_5m_m0_kal",
            width=25.0,
            signal_interval="5m",
            completion_margin=0.0,
            signal_source="kalman",
        )
        hull_sig = cast("TradeSignal", FakeHullSignal())
        kal_sig = cast("TradeSignal", FakeKalmanSignal())
        rig_sig = cast("TradeSignal", RigSig())
        assert signal_matches(hull_arm, hull_sig)
        assert not signal_matches(hull_arm, kal_sig)
        assert signal_matches(kal_arm, kal_sig)
        assert not signal_matches(kal_arm, hull_sig)
        # rig stubs without .engine stay hull-family
        assert signal_matches(hull_arm, rig_sig)
        assert not signal_matches(kal_arm, rig_sig)

    def test_simulator_routes_families_to_their_arms(self) -> None:
        sim = ButterflySimulator(default_variants())
        signals = cast("list[TradeSignal]", [FakeHullSignal(), FakeKalmanSignal()])
        sim.on_snapshot(TS, 7740.0, quotes_for(7740.0), signals)
        by_variant: dict[str, int] = {}
        for s in sim.structures:
            by_variant[s.variant] = by_variant.get(s.variant, 0) + 1
        # one entry per arm: hull arms from the hull signal, kal arms from
        # the kalman signal — never two entries in one arm
        assert by_variant.get("w25_5m_m0") == 1
        assert by_variant.get("w25_5m_m0_kal") == 1
        assert by_variant.get("w25_5m_m0_kal_ef5") == 1
        kal_rows = [s for s in sim.structures if s.variant.startswith("w25_5m_m0_kal")]
        assert all(s.signal_trigger == "kalman_flip" for s in kal_rows)
