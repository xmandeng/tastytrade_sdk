"""Fill-persistence overlay (user-approved 2026-08-29): a completion only
fills after the threshold holds N consecutive snapshots — the resting-limit
execution model bracketing the ephemeral-freebie edge."""

from datetime import datetime, timedelta, timezone
from typing import cast

from tastytrade.analytics.engines.models import TradeSignal

from research.tt156_zero_dte_butterfly.config import VariantConfig, default_variants
from research.tt156_zero_dte_butterfly.simulator import ButterflySimulator

TS = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)  # 11:00 ET


class KalOpen:
    eventSymbol = "SPX{=5m}"
    signal_type = "OPEN"
    direction = "BEARISH"
    trigger = "kalman_flip"
    engine = "kalman"


def p_variant(n: int) -> VariantConfig:
    return VariantConfig(
        name=f"w25_5m_m0_kal_p{n}",
        width=25.0,
        signal_interval="5m",
        completion_margin=0.0,
        signal_source="kalman",
        fill_persistence=n,
    )


def quotes_skewed(spot: float, slope: float) -> dict:
    """Moneyness-skewed extrinsic; the skew slope sets the vertical credit
    (credit ≈ slope × width per side, so total ≈ 2 × slope × width)."""
    q = {}
    start = (int(spot) - 200) // 5 * 5
    for k in range(start, start + 405, 5):
        extrinsic = max(0.5, 16.0 - slope * abs(k - spot))
        for cp in ("C", "P"):
            intrinsic = max(spot - k, 0.0) if cp == "C" else max(k - spot, 0.0)
            mid_val = intrinsic + extrinsic
            q[(float(k), cp)] = {"bid": mid_val - 0.2, "ask": mid_val + 0.2}
    return q


RICH = quotes_skewed(7700.0, 0.6)  # total ≈ 30 > 25 — threshold met
POOR = quotes_skewed(7700.0, 0.2)  # total ≈ 10 < 25 — threshold not met


def enter(sim: ButterflySimulator) -> None:
    sim.on_snapshot(TS, 7700.0, RICH, cast("list[TradeSignal]", [KalOpen()]))


class TestFillPersistence:
    def test_p1_completes_on_first_touch(self) -> None:
        sim = ButterflySimulator([p_variant(1)])
        enter(sim)
        assert sim.structures[0].status == "COMPLETED"

    def test_p2_needs_two_consecutive_snapshots(self) -> None:
        sim = ButterflySimulator([p_variant(2)])
        enter(sim)
        s = sim.structures[0]
        assert s.status == "OPEN"  # first touch — streak 1 of 2
        sim.on_snapshot(TS + timedelta(seconds=15), 7700.0, RICH, [])
        assert s.status == "COMPLETED"

    def test_streak_resets_when_threshold_lost(self) -> None:
        sim = ButterflySimulator([p_variant(2)])
        enter(sim)
        s = sim.structures[0]
        sim.on_snapshot(TS + timedelta(seconds=15), 7700.0, POOR, [])  # reset
        sim.on_snapshot(TS + timedelta(seconds=30), 7700.0, RICH, [])  # streak 1
        assert s.status == "OPEN"
        sim.on_snapshot(TS + timedelta(seconds=45), 7700.0, RICH, [])  # streak 2
        assert s.status == "COMPLETED"

    def test_default_grid_includes_persistence_arms(self) -> None:
        by_name = {v.name: v for v in default_variants()}
        assert by_name["w25_5m_m0_kal_p2"].fill_persistence == 2
        assert by_name["w25_5m_m0_kal_p4"].fill_persistence == 4
        assert by_name["w25_5m_m0_kal"].fill_persistence == 1
