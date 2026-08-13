"""Unit tests for the TT-156 half-width credit strike arm."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tastytrade.analytics.engines.models import TradeSignal

from research.tt156_zero_dte_butterfly.config import VariantConfig, default_variants
from research.tt156_zero_dte_butterfly.simulator import (
    ButterflySimulator,
    Quotes,
    halfwidth_entry,
)

ET = ZoneInfo("America/New_York")


def make_signal(signal_type: str, direction: str, interval: str = "m") -> TradeSignal:
    return TradeSignal(
        eventSymbol=f"SPX{{={interval}}}",
        start_time=datetime(2026, 8, 11, 12, 31, tzinfo=ET),
        label=f"{signal_type} {direction}",
        signal_type=signal_type,
        direction=direction,
        engine="hull_macd",
        hull_direction="Down" if direction == "BEARISH" else "Up",
        hull_value=7300.0,
        macd_value=-1.0,
        macd_signal=0.0,
        macd_histogram=-1.0,
        close_price=7300.0,
        trigger="confluence",
    )


def chain_quotes(prices: dict[tuple[float, str], tuple[float, float]]) -> Quotes:
    return {key: {"bid": bid, "ask": ask} for key, (bid, ask) in prices.items()}


# Bearish w10 chain around spot 7301: ATM (7300/7310) collects 4.0 — under
# half-width — and one strike deeper (7295/7305) collects 5.5, which clears.
BEARISH_CHAIN = chain_quotes(
    {
        (7300.0, "C"): (7.0, 7.4),
        (7310.0, "C"): (3.0, 3.4),
        (7295.0, "C"): (9.8, 10.2),
        (7305.0, "C"): (4.3, 4.7),
    }
)


def hw_variant() -> VariantConfig:
    return VariantConfig(
        name="w10_m_m0_hw",
        width=10.0,
        signal_interval="m",
        completion_margin=0.0,
        strike_rule="halfwidth",
    )


def test_grid_has_both_arms_and_atm_names_unchanged():
    variants = default_variants()
    assert len(variants) == 30  # 12 atm + 12 hw + 6 gate-enforced hw
    atm = [v for v in variants if v.strike_rule == "atm"]
    hw = [v for v in variants if v.strike_rule == "halfwidth" and not v.gate_enforced]
    ghw = [v for v in variants if v.gate_enforced]
    assert len(atm) == len(hw) == 12
    assert len(ghw) == 6
    assert all(not v.name.endswith("_hw") for v in atm)
    assert all(v.name.endswith("_hw") for v in hw)
    assert all(v.name.endswith("_ghw") for v in ghw)
    # historical ATM names preserved exactly
    assert {v.name for v in atm} == {
        f"w{w:g}_{i}_m{m:g}"
        for w in (10.0, 25.0, 50.0)
        for i in ("m", "5m")
        for m in (0.0, 2.0)
    }


def test_halfwidth_entry_steps_itm_until_credit_clears():
    picked = halfwidth_entry("BEARISH", 7301.0, 10.0, BEARISH_CHAIN)
    assert picked is not None
    strike, credit, legs = picked
    assert strike == 7295.0
    assert credit == pytest.approx(5.5)
    assert [(leg.occ_strike, leg.action) for leg in legs] == [
        (7295.0, "STO"),
        (7305.0, "BTO"),
    ]


def test_halfwidth_entry_uses_atm_when_it_already_clears():
    quotes = chain_quotes({(7300.0, "C"): (9.0, 9.4), (7310.0, "C"): (3.0, 3.4)})
    picked = halfwidth_entry("BEARISH", 7301.0, 10.0, quotes)
    assert picked is not None
    assert picked[0] == 7300.0
    assert picked[1] == pytest.approx(6.0)


def test_halfwidth_entry_bullish_steps_up_through_puts():
    quotes = chain_quotes(
        {
            (7300.0, "P"): (5.8, 6.2),
            (7290.0, "P"): (1.8, 2.2),
            (7305.0, "P"): (9.8, 10.2),
            (7295.0, "P"): (4.2, 4.6),
        }
    )
    picked = halfwidth_entry("BULLISH", 7299.0, 10.0, quotes)
    assert picked is not None
    assert picked[0] == 7305.0
    assert picked[1] == pytest.approx(5.6)


def test_halfwidth_entry_returns_none_when_nothing_clears():
    quotes = chain_quotes({(7300.0, "C"): (7.0, 7.4), (7310.0, "C"): (3.0, 3.4)})
    assert halfwidth_entry("BEARISH", 7301.0, 10.0, quotes) is None


def test_try_enter_dispatches_on_strike_rule():
    sim = ButterflySimulator([hw_variant()])
    ts = datetime(2026, 8, 11, 12, 31, tzinfo=ET)
    sim.on_snapshot(ts, 7301.0, BEARISH_CHAIN, [make_signal("OPEN", "BEARISH")])
    assert len(sim.structures) == 1
    structure = sim.structures[0]
    assert structure.short_strike == 7295.0
    assert structure.entry_credit == pytest.approx(5.5)
    assert structure.entry_credit > structure.width / 2


def test_try_enter_skips_when_no_strike_clears():
    sim = ButterflySimulator([hw_variant()])
    ts = datetime(2026, 8, 11, 12, 31, tzinfo=ET)
    quotes = chain_quotes({(7300.0, "C"): (7.0, 7.4), (7310.0, "C"): (3.0, 3.4)})
    sim.on_snapshot(ts, 7301.0, quotes, [make_signal("OPEN", "BEARISH")])
    assert sim.structures == []
    assert sim.skipped_entries == 1
