"""Gate-enforced half-width arm (_ghw): enters only imminent/near clusters,
half-width strike rule; report arms stay disjoint (TT-156, user directive
2026-08-13)."""

from datetime import datetime, timezone
from typing import cast

from tastytrade.analytics.engines.models import TradeSignal

from research.tt156_zero_dte_butterfly.config import default_variants
from research.tt156_zero_dte_butterfly.report import arm_of
from research.tt156_zero_dte_butterfly.simulator import ButterflySimulator

TS = datetime(2026, 8, 13, 16, 30, tzinfo=timezone.utc)  # 12:30 ET


class FakeSignal:
    eventSymbol = "SPX{=m}"
    signal_type = "OPEN"
    direction = "BULLISH"
    trigger = "confluence"


def quotes_for(spot: float) -> dict:
    # deep put quotes so the half-width rule can find a qualifying strike
    q = {}
    for k in range(int(spot) - 200, int(spot) + 205, 5):
        intrinsic = max(k - spot, 0.0)
        q[(float(k), "P")] = {"bid": intrinsic + 3.0, "ask": intrinsic + 3.4}
        q[(float(k), "C")] = {
            "bid": max(spot - k, 0) + 3.0,
            "ask": max(spot - k, 0) + 3.4,
        }
    return q


GATED_CTX = {
    "hist_5m": -0.5,
    "slope_5m": 0.1,
    "flip_eta_5m": 5.0,
    "hist_1m": 0.2,
    "slope_1m": 0.05,
    "flip_eta_1m": None,
}
FIRM_CTX = {
    "hist_5m": -2.0,
    "slope_5m": 0.01,
    "flip_eta_5m": 200.0,
    "hist_1m": 0.2,
    "slope_1m": 0.05,
    "flip_eta_1m": None,
}


def ghw_variants():
    return [v for v in default_variants() if v.gate_enforced]


class TestVariantGrid:
    def test_six_ghw_variants_exist(self) -> None:
        vs = ghw_variants()
        assert len(vs) == 6
        assert all(v.strike_rule == "halfwidth" for v in vs)
        assert all(v.signal_interval == "m" for v in vs)
        assert all(v.name.endswith("_ghw") for v in vs)

    def test_arm_classification_disjoint(self) -> None:
        assert arm_of("w10_m_m0_ghw") == "ghw"
        assert arm_of("w10_m_m0_hw") == "hw"
        assert arm_of("w10_m_m0") == "atm"


class TestEnforcement:
    def enter(self, ctx):
        sim = ButterflySimulator(ghw_variants())
        signals = cast("list[TradeSignal]", [FakeSignal()])
        sim.on_snapshot(TS, 7740.0, quotes_for(7740.0), signals, ctx)
        return sim.structures

    def test_enters_on_gated_cluster(self) -> None:
        structures = self.enter(GATED_CTX)
        assert len(structures) == 6
        assert all(s.gate_bucket == "near" for s in structures)
        # half-width rule honored: entry credit > width / 2
        assert all(s.entry_credit > s.width / 2 for s in structures)

    def test_skips_firm_cluster(self) -> None:
        assert self.enter(FIRM_CTX) == []

    def test_skips_when_gate_context_missing(self) -> None:
        assert self.enter(None) == []

    def test_unenforced_variants_still_enter_firm(self) -> None:
        atm = [v for v in default_variants() if not v.gate_enforced]
        sim = ButterflySimulator(atm)
        signals = cast("list[TradeSignal]", [FakeSignal()])
        sim.on_snapshot(TS, 7740.0, quotes_for(7740.0), signals, FIRM_CTX)
        assert len(sim.structures) > 0
        assert all(s.gate_bucket == "firm" for s in sim.structures)
