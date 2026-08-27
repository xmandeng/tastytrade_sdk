"""Early-fly conversion arm (_ef5): at 5 pts adverse, buy the counter side
now — bounded deficit, tent kept (user-approved 2026-08-27)."""

from datetime import datetime, timezone
from typing import cast

from tastytrade.analytics.engines.models import TradeSignal

from research.tt156_zero_dte_butterfly.config import VariantConfig, default_variants
from research.tt156_zero_dte_butterfly.simulator import ButterflySimulator

TS = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)  # 11:00 ET


class FakeSignal:
    eventSymbol = "SPX{=5m}"
    signal_type = "OPEN"
    direction = "BEARISH"
    trigger = "hull_flip"


def ef_variant() -> VariantConfig:
    return VariantConfig(
        name="w25_5m_m0_ef5",
        width=25.0,
        signal_interval="5m",
        completion_margin=0.0,
        early_fly_adverse_pts=5.0,
    )


def quotes_at(spot: float, base: float = 4.0) -> dict:
    """Synthetic chain with moneyness-skewed extrinsic: entry verticals
    collect a small positive credit, but never enough to complete normally
    (entry + counter << width)."""
    q = {}
    start = (int(spot) - 200) // 5 * 5
    for k in range(start, start + 405, 5):
        extrinsic = max(0.5, base - 0.02 * abs(k - spot))
        for cp in ("C", "P"):
            intrinsic = max(spot - k, 0.0) if cp == "C" else max(k - spot, 0.0)
            mid_val = intrinsic + extrinsic
            q[(float(k), cp)] = {"bid": mid_val - 0.2, "ask": mid_val + 0.2}
    return q


class TestEarlyFly:
    def test_default_grid_includes_ef_arm(self) -> None:
        names = [v.name for v in default_variants()]
        assert "w25_5m_m0_ef5" in names

    def test_converts_at_adverse_trigger(self) -> None:
        sim = ButterflySimulator([ef_variant()])
        signals = cast("list[TradeSignal]", [FakeSignal()])
        sim.on_snapshot(TS, 7700.0, quotes_at(7700.0), signals)
        assert len(sim.structures) == 1
        s = sim.structures[0]
        assert s.status == "OPEN"
        # spot rips 12 pts against the short call spread -> adverse > 5 pts
        sim.on_snapshot(TS, 7712.0, quotes_at(7712.0), [])
        assert s.status == "COMPLETED"
        total = s.entry_credit + (s.completion_credit or 0.0)
        assert total < s.width  # deficit fly: locked below the lossless bar

    def test_no_conversion_below_trigger(self) -> None:
        sim = ButterflySimulator([ef_variant()])
        signals = cast("list[TradeSignal]", [FakeSignal()])
        sim.on_snapshot(TS, 7700.0, quotes_at(7700.0), signals)
        sim.on_snapshot(TS, 7702.0, quotes_at(7702.0), [])  # ~2 pts adverse
        assert sim.structures[0].status == "OPEN"

    def test_plain_variant_never_converts_early(self) -> None:
        plain = VariantConfig(
            name="w25_5m_m0", width=25.0, signal_interval="5m", completion_margin=0.0
        )
        sim = ButterflySimulator([plain])
        signals = cast("list[TradeSignal]", [FakeSignal()])
        sim.on_snapshot(TS, 7700.0, quotes_at(7700.0), signals)
        sim.on_snapshot(TS, 7712.0, quotes_at(7712.0), [])
        assert sim.structures[0].status == "OPEN"
