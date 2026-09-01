"""Pin-fly tracked arms (2026-08-31 condor-overlay study): 14:00 long ATM
butterfly, defined debit, hold to settlement; triggers all / no-tent /
no-tent+mid-range."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from research.tt156_zero_dte_butterfly.pinfly import (
    PinFlySimulator,
    default_pinfly_arms,
    fly_debit,
)

ET = ZoneInfo("America/New_York")


def quotes_for(spot: float) -> dict:
    """Call quotes with moneyness-decaying extrinsic: ATM richest, wings
    cheaper — a positive fly debit."""
    q = {}
    base = (int(spot) - 100) // 5 * 5
    for k in range(base, base + 205, 5):
        extrinsic = max(0.4, 12.0 - 0.3 * abs(k - spot))
        intrinsic = max(spot - k, 0.0)
        mid_val = intrinsic + extrinsic
        q[(float(k), "C")] = {"bid": mid_val - 0.2, "ask": mid_val + 0.2}
    return q


def at(hh: int, mm: int) -> datetime:
    return datetime(2026, 8, 31, hh, mm, tzinfo=ET)


def sim(tent: bool = False) -> tuple[PinFlySimulator, list[dict]]:
    events: list[dict] = []
    s = PinFlySimulator(
        default_pinfly_arms(), tent_exists=lambda: tent, event_sink=events.append
    )
    return s, events


class TestFlyDebit:
    def test_prices_positive_debit_at_atm(self):
        priced = fly_debit(quotes_for(7700.0), 7700.0, 25.0)
        assert priced is not None
        debit, body, legs = priced
        assert body == 7700.0
        # intrinsic telescopes to +25 (lo wing ITM); extrinsic convexity
        # 4.5 + 4.5 - 2*12 = -15 -> net 10.0
        assert debit == pytest.approx(10.0, abs=1e-6)
        assert [(leg.occ_strike, leg.action) for leg in legs] == [
            (7675.0, "BTO"),
            (7700.0, "STO"),
            (7700.0, "STO"),
            (7725.0, "BTO"),
        ]


class TestTriggers:
    def test_all_and_notent_enter_when_no_tent(self):
        s, events = sim(tent=False)
        s.on_snapshot(at(10, 0), 7700.0, {})  # range tracking
        s.on_snapshot(at(14, 0), 7700.0, quotes_for(7700.0))
        names = {e["variant"] for e in events}
        # flat range -> pos treated as mid-range, so all three fire
        assert names == {"pinfly25_all", "pinfly25_notent", "pinfly25_notent_mid"}

    def test_tent_suppresses_conditional_arms(self):
        s, events = sim(tent=True)
        s.on_snapshot(at(10, 0), 7700.0, {})
        s.on_snapshot(at(14, 0), 7700.0, quotes_for(7700.0))
        assert {e["variant"] for e in events} == {"pinfly25_all"}

    def test_mid_range_condition(self):
        s, events = sim(tent=False)
        s.on_snapshot(at(10, 0), 7660.0, {})  # low
        s.on_snapshot(at(11, 0), 7740.0, {})  # high
        s.on_snapshot(at(14, 0), 7735.0, quotes_for(7735.0))  # at the edge
        names = {e["variant"] for e in events}
        assert "pinfly25_notent" in names
        assert "pinfly25_notent_mid" not in names

    def test_restart_past_window_never_enters(self):
        s, events = sim()
        s.on_snapshot(at(14, 20), 7700.0, quotes_for(7700.0))
        assert events == []
        s.on_snapshot(at(14, 21), 7700.0, quotes_for(7700.0))
        assert events == []

    def test_single_entry_per_day(self):
        s, events = sim()
        s.on_snapshot(at(14, 0), 7700.0, quotes_for(7700.0))
        s.on_snapshot(at(14, 5), 7700.0, quotes_for(7700.0))
        assert len([e for e in events if e["variant"] == "pinfly25_all"]) == 1


class TestSettlement:
    def test_pnl_is_payoff_minus_debit(self):
        s, events = sim()
        s.on_snapshot(at(14, 0), 7700.0, quotes_for(7700.0))
        s.settle(at(16, 15), 7705.0)  # 5 pts from the 7700 body
        settled = [e for e in events if e["event"] == "SETTLEMENT"]
        assert settled
        for e in settled:
            assert e["pnl_points"] == pytest.approx((25.0 - 5.0) - 10.0, abs=1e-6)
            assert e["status"] == "SETTLED"

    def test_max_loss_is_the_debit(self):
        s, events = sim()
        s.on_snapshot(at(14, 0), 7700.0, quotes_for(7700.0))
        s.settle(at(16, 15), 7800.0)  # far outside the wings
        settled = [e for e in events if e["event"] == "SETTLEMENT"]
        for e in settled:
            assert e["pnl_points"] == pytest.approx(-10.0, abs=1e-6)
