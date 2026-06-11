"""Unit tests for the TT-156 butterfly legging simulator."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tastytrade.analytics.engines.models import TradeSignal

from research.tt156_zero_dte_butterfly.config import VariantConfig
from research.tt156_zero_dte_butterfly.simulator import (
    ButterflySimulator,
    Quotes,
    atm_strike,
    leg_mid,
    vertical_credit,
)

ET = ZoneInfo("America/New_York")


def make_signal(signal_type: str, direction: str, interval: str = "5m") -> TradeSignal:
    return TradeSignal(
        eventSymbol=f"SPX{{={interval}}}",
        start_time=datetime(2026, 6, 11, 10, 30, tzinfo=ET),
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


def quote(bid: float, ask: float) -> dict[str, float | None]:
    return {"bid": bid, "ask": ask}


def chain_quotes(prices: dict[tuple[float, str], tuple[float, float]]) -> Quotes:
    return {key: quote(bid, ask) for key, (bid, ask) in prices.items()}


@pytest.fixture
def variant() -> VariantConfig:
    return VariantConfig(
        name="w25_5m_m0", width=25.0, signal_interval="5m", completion_margin=0.0
    )


def test_atm_strike_rounds_to_five():
    assert atm_strike(7302.4) == 7300.0
    assert atm_strike(7303.0) == 7305.0


def test_leg_mid_requires_ask():
    assert leg_mid(quote(1.0, 2.0)) == 1.5
    assert leg_mid({"bid": 1.0, "ask": None}) is None
    assert leg_mid({"bid": None, "ask": 2.0}) == 1.0


def test_vertical_credit():
    quotes = chain_quotes({(7300.0, "C"): (10.0, 11.0), (7325.0, "C"): (3.0, 4.0)})
    priced = vertical_credit(quotes, 7300.0, 7325.0, "C")
    assert priced is not None
    credit, legs = priced
    assert credit == pytest.approx(7.0)
    assert legs[0].action == "STO" and legs[1].action == "BTO"


def test_entry_completion_and_settlement(variant: VariantConfig):
    events: list[dict] = []
    sim = ButterflySimulator([variant], event_sink=events.append)
    ts = datetime(2026, 6, 11, 10, 30, tzinfo=ET)

    # Bearish entry: ATM 7300, bear call 7300/7325 for 11.0 credit
    entry_quotes = chain_quotes(
        {
            (7300.0, "C"): (14.0, 15.0),
            (7325.0, "C"): (3.0, 4.0),
            (7300.0, "P"): (10.0, 11.0),
            (7275.0, "P"): (4.0, 5.0),
        }
    )
    sim.on_snapshot(ts, 7301.0, entry_quotes, [make_signal("OPEN", "BEARISH")])
    assert len(sim.structures) == 1
    structure = sim.structures[0]
    assert structure.entry_credit == pytest.approx(11.0)
    # Counter (bull put 7300/7275) credit 6.0 — total 17.0 < 25: no completion
    assert structure.status == "OPEN"

    # SPX drops: the put spread now sells for 15.0 → total 26.0 >= 25
    ts2 = datetime(2026, 6, 11, 11, 30, tzinfo=ET)
    completion_quotes = chain_quotes(
        {
            (7300.0, "C"): (4.0, 5.0),
            (7325.0, "C"): (1.0, 2.0),
            (7300.0, "P"): (19.0, 20.0),
            (7275.0, "P"): (4.0, 5.0),
        }
    )
    sim.on_snapshot(ts2, 7270.0, completion_quotes, [])
    assert structure.status == "COMPLETED"
    assert structure.completion_credit == pytest.approx(15.0)

    # Settlement at 7290: payoff = 26 - |7290-7300| = 16
    sim.settle(datetime(2026, 6, 11, 16, 0, tzinfo=ET), 7290.0)
    assert structure.status == "SETTLED"
    assert structure.pnl_points == pytest.approx(16.0)
    assert {e["event"] for e in events} == {"ENTRY", "COMPLETION", "SETTLEMENT"}


def test_close_on_opposing_signal(variant: VariantConfig):
    sim = ButterflySimulator([variant])
    ts = datetime(2026, 6, 11, 10, 30, tzinfo=ET)
    quotes = chain_quotes(
        {
            (7300.0, "C"): (14.0, 15.0),
            (7325.0, "C"): (3.0, 4.0),
            (7300.0, "P"): (10.0, 11.0),
            (7275.0, "P"): (4.0, 5.0),
        }
    )
    sim.on_snapshot(ts, 7301.0, quotes, [make_signal("OPEN", "BEARISH")])
    structure = sim.structures[0]

    # CLOSE signal: buy back at current mid (cost 11.0) → P&L 0
    ts2 = datetime(2026, 6, 11, 12, 0, tzinfo=ET)
    sim.on_snapshot(ts2, 7301.0, quotes, [make_signal("CLOSE", "BEARISH")])
    assert structure.status == "CLOSED"
    assert structure.pnl_points == pytest.approx(0.0)
    assert structure.close_reason == "signal_confluence"


def test_forced_close_after_1545(variant: VariantConfig):
    sim = ButterflySimulator([variant])
    quotes = chain_quotes(
        {
            (7300.0, "C"): (14.0, 15.0),
            (7325.0, "C"): (3.0, 4.0),
            (7300.0, "P"): (10.0, 11.0),
            (7275.0, "P"): (4.0, 5.0),
        }
    )
    ts = datetime(2026, 6, 11, 14, 0, tzinfo=ET)
    sim.on_snapshot(ts, 7301.0, quotes, [make_signal("OPEN", "BEARISH")])
    ts2 = datetime(2026, 6, 11, 15, 46, tzinfo=ET)
    sim.on_snapshot(ts2, 7301.0, quotes, [])
    assert sim.structures[0].status == "CLOSED"
    assert sim.structures[0].close_reason == "forced_eod"


def test_signals_only_route_to_matching_interval():
    v1 = VariantConfig(name="a", width=25.0, signal_interval="m", completion_margin=0.0)
    sim = ButterflySimulator([v1])
    quotes = chain_quotes({(7300.0, "C"): (14.0, 15.0), (7325.0, "C"): (3.0, 4.0)})
    ts = datetime(2026, 6, 11, 10, 30, tzinfo=ET)
    sim.on_snapshot(ts, 7301.0, quotes, [make_signal("OPEN", "BEARISH", interval="5m")])
    assert sim.structures == []
