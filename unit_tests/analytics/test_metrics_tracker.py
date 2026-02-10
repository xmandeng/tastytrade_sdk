"""Tests for SecurityMetrics, MetricsTracker, and MetricsEventProcessor."""

from datetime import datetime
from typing import Any

import pandas as pd

from tastytrade.accounts.models import InstrumentType, Position, QuantityDirection
from tastytrade.analytics.metrics import (
    DELTA_1_TYPES,
    OPTION_TYPES,
    MetricsTracker,
    SecurityMetrics,
)
from tastytrade.messaging.models.events import GreeksEvent, QuoteEvent, TradeEvent
from tastytrade.messaging.processors.metrics import MetricsEventProcessor


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_position_json(**overrides: Any) -> dict[str, Any]:
    """Factory: hyphenated-key dict matching real API shape."""
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": "SPY",
        "instrument-type": "Equity",
        "underlying-symbol": "SPY",
        "quantity": "100.0",
        "quantity-direction": "Long",
        "multiplier": "1",
        "close-price": "690.62",
        "average-open-price": "664.93",
        "mark": "690.00",
        "mark-price": "690.00",
        "average-daily-market-close-price": "689.00",
        "average-yearly-market-close-price": "680.00",
        "is-frozen": False,
        "is-suppressed": False,
        "restricted-quantity": "0.0",
        "cost-effect": "Debit",
        "streamer-symbol": "SPY",
        "realized-day-gain": "0.0",
        "realized-day-gain-effect": "None",
        "realized-day-gain-date": "2026-02-01",
        "realized-today": "0.0",
        "realized-today-effect": "None",
        "realized-today-date": "2026-02-01",
        "created-at": "2026-01-15T10:30:00Z",
        "updated-at": "2026-02-01T14:00:00Z",
    }
    base.update(overrides)
    return base


def make_position(**overrides: Any) -> Position:
    """Create a Position model from factory defaults + overrides."""
    return Position.model_validate(make_position_json(**overrides))


def make_quote(symbol: str, bid: float, ask: float) -> QuoteEvent:
    """Create a QuoteEvent with required fields."""
    return QuoteEvent(
        eventSymbol=symbol,
        bidPrice=bid,
        askPrice=ask,
        bidSize=100.0,
        askSize=200.0,
    )


def make_greeks(symbol: str, **overrides: Any) -> GreeksEvent:
    """Create a GreeksEvent with realistic option Greeks values.

    Note: FloatFieldMixin rounds all values to MAX_PRECISION (2 decimals),
    so default values are chosen to survive rounding.
    """
    defaults: dict[str, Any] = {
        "eventSymbol": symbol,
        "delta": -0.35,
        "gamma": 0.04,
        "theta": -0.08,
        "vega": 0.15,
        "rho": -0.02,
        "volatility": 0.28,
    }
    defaults.update(overrides)
    return GreeksEvent(**defaults)


def make_equity_option_position(**overrides: Any) -> Position:
    """Create an Equity Option position from factory defaults."""
    defaults: dict[str, Any] = {
        "instrument-type": "Equity Option",
        "streamer-symbol": ".MCD260320P305",
        "underlying-symbol": "MCD",
        "multiplier": "100",
        "quantity-direction": "Short",
    }
    defaults.update(overrides)
    return make_position(symbol="MCD   260320P00305000", **defaults)


def make_future_option_position(**overrides: Any) -> Position:
    """Create a Future Option position from factory defaults."""
    defaults: dict[str, Any] = {
        "instrument-type": "Future Option",
        "streamer-symbol": "./EX3H26P6450:XCME",
        "underlying-symbol": "/MESM6",
        "multiplier": "5",
        "quantity-direction": "Short",
    }
    defaults.update(overrides)
    return make_position(symbol="./MESM6EX3H6 260320P6450", **defaults)


# ---------------------------------------------------------------------------
# SecurityMetrics model tests
# ---------------------------------------------------------------------------


def test_security_metrics_defaults() -> None:
    metrics = SecurityMetrics(
        symbol="SPY",
        streamer_symbol="SPY",
        instrument_type=InstrumentType.EQUITY,
        quantity=100.0,
        quantity_direction=QuantityDirection.LONG,
    )
    assert metrics.bid_price is None
    assert metrics.ask_price is None
    assert metrics.mid_price is None
    assert metrics.delta is None
    assert metrics.price_updated_at is None


def test_security_metrics_is_mutable() -> None:
    metrics = SecurityMetrics(
        symbol="SPY",
        streamer_symbol="SPY",
        instrument_type=InstrumentType.EQUITY,
        quantity=100.0,
        quantity_direction=QuantityDirection.LONG,
    )
    metrics.bid_price = 600.0
    assert metrics.bid_price == 600.0


# ---------------------------------------------------------------------------
# load_positions — delta-1 Greeks defaults
# ---------------------------------------------------------------------------


def test_load_positions_equity_long_delta_positive_one() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    sec = tracker.securities["SPY"]
    assert sec.delta == 1.0
    assert sec.gamma == 0.0
    assert sec.theta == 0.0
    assert sec.vega == 0.0
    assert sec.rho == 0.0
    assert sec.implied_volatility is None


def test_load_positions_equity_short_delta_negative_one() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position(**{"quantity-direction": "Short"})])
    sec = tracker.securities["SPY"]
    assert sec.delta == -1.0


def test_load_positions_zero_direction_delta_zero() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [make_position(**{"quantity-direction": "Zero", "quantity": "0.0"})]
    )
    sec = tracker.securities["SPY"]
    assert sec.delta == 0.0


def test_load_positions_future_gets_delta_1_defaults() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(
                symbol="/MESM6",
                **{
                    "instrument-type": "Future",
                    "streamer-symbol": "/MESM6",
                    "underlying-symbol": "/MESM6",
                    "multiplier": "5",
                },
            )
        ]
    )
    sec = tracker.securities["/MESM6"]
    assert sec.delta == 1.0
    assert sec.gamma == 0.0
    assert sec.theta == 0.0


def test_load_positions_cryptocurrency_gets_delta_1_defaults() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(
                symbol="BTC/USD",
                **{
                    "instrument-type": "Cryptocurrency",
                    "streamer-symbol": "BTC/USD:CXTALP",
                    "underlying-symbol": "BTC/USD",
                },
            )
        ]
    )
    sec = tracker.securities["BTC/USD:CXTALP"]
    assert sec.delta == 1.0
    assert sec.gamma == 0.0


# ---------------------------------------------------------------------------
# load_positions — options get None Greeks
# ---------------------------------------------------------------------------


def test_load_positions_equity_option_greeks_none() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(
                symbol="MCD   260320P00305000",
                **{
                    "instrument-type": "Equity Option",
                    "streamer-symbol": ".MCD260320P305",
                    "underlying-symbol": "MCD",
                    "multiplier": "100",
                    "quantity-direction": "Short",
                },
            )
        ]
    )
    sec = tracker.securities[".MCD260320P305"]
    assert sec.delta is None
    assert sec.gamma is None
    assert sec.theta is None
    assert sec.vega is None
    assert sec.rho is None
    assert sec.implied_volatility is None


def test_load_positions_future_option_greeks_none() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(
                symbol="./MESM6EX3H6 260320P6450",
                **{
                    "instrument-type": "Future Option",
                    "streamer-symbol": "./EX3H26P6450:XCME",
                    "underlying-symbol": "/MESM6",
                    "multiplier": "5",
                    "quantity-direction": "Short",
                },
            )
        ]
    )
    sec = tracker.securities["./EX3H26P6450:XCME"]
    assert sec.delta is None
    assert sec.gamma is None
    assert sec.greeks_updated_at is None


# ---------------------------------------------------------------------------
# load_positions — edge cases
# ---------------------------------------------------------------------------


def test_load_positions_skips_no_streamer_symbol() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(
                symbol="CSCO",
                **{"streamer-symbol": None, "underlying-symbol": "CSCO"},
            )
        ]
    )
    assert len(tracker.securities) == 0


def test_load_positions_multiple_positions() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(symbol="SPY", **{"streamer-symbol": "SPY"}),
            make_position(symbol="QQQ", **{"streamer-symbol": "QQQ"}),
            make_position(
                symbol="MCD   260320P00305000",
                **{
                    "instrument-type": "Equity Option",
                    "streamer-symbol": ".MCD260320P305",
                    "underlying-symbol": "MCD",
                },
            ),
        ]
    )
    assert len(tracker.securities) == 3
    assert "SPY" in tracker.securities
    assert "QQQ" in tracker.securities
    assert ".MCD260320P305" in tracker.securities


def test_load_positions_sets_position_updated_at() -> None:
    before = datetime.now()
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    after = datetime.now()
    sec = tracker.securities["SPY"]
    assert sec.position_updated_at is not None
    assert before <= sec.position_updated_at <= after


def test_load_positions_market_data_initially_none() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    sec = tracker.securities["SPY"]
    assert sec.bid_price is None
    assert sec.ask_price is None
    assert sec.mid_price is None
    assert sec.price_updated_at is None


def test_load_positions_greeks_updated_at_set_for_delta1() -> None:
    before = datetime.now()
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    after = datetime.now()
    sec = tracker.securities["SPY"]
    assert sec.greeks_updated_at is not None
    assert before <= sec.greeks_updated_at <= after


# ---------------------------------------------------------------------------
# on_quote_event
# ---------------------------------------------------------------------------


def test_on_quote_event_updates_bid_ask_mid() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    tracker.on_quote_event(make_quote("SPY", bid=600.50, ask=600.75))
    sec = tracker.securities["SPY"]
    assert sec.bid_price == 600.50
    assert sec.ask_price == 600.75
    assert sec.mid_price == 600.62  # round((600.50 + 600.75) / 2, 2)


def test_on_quote_event_updates_price_timestamp() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    before = datetime.now()
    tracker.on_quote_event(make_quote("SPY", bid=600.0, ask=601.0))
    after = datetime.now()
    sec = tracker.securities["SPY"]
    assert sec.price_updated_at is not None
    assert before <= sec.price_updated_at <= after


def test_on_quote_event_unknown_symbol_ignored() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    tracker.on_quote_event(make_quote("MSFT", bid=400.0, ask=400.5))
    assert "MSFT" not in tracker.securities
    assert len(tracker.securities) == 1


def test_on_quote_event_preserves_greeks() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    tracker.on_quote_event(make_quote("SPY", bid=600.0, ask=601.0))
    sec = tracker.securities["SPY"]
    assert sec.delta == 1.0
    assert sec.gamma == 0.0


# ---------------------------------------------------------------------------
# on_position_update
# ---------------------------------------------------------------------------


def test_on_position_update_merges_quantity_change() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position(quantity="100.0")])
    tracker.on_quote_event(make_quote("SPY", bid=600.0, ask=601.0))

    updated = make_position(quantity="200.0")
    tracker.on_position_update(updated)

    sec = tracker.securities["SPY"]
    assert sec.quantity == 200.0
    # Market data preserved
    assert sec.bid_price == 600.0
    assert sec.ask_price == 601.0
    # Greeks preserved
    assert sec.delta == 1.0


def test_on_position_update_new_position_added() -> None:
    tracker = MetricsTracker()
    tracker.on_position_update(make_position())
    assert "SPY" in tracker.securities
    sec = tracker.securities["SPY"]
    assert sec.delta == 1.0


def test_on_position_update_skips_no_streamer_symbol() -> None:
    tracker = MetricsTracker()
    tracker.on_position_update(make_position(**{"streamer-symbol": None}))
    assert len(tracker.securities) == 0


def test_on_position_update_sets_position_updated_at() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    original_ts = tracker.securities["SPY"].position_updated_at

    updated = make_position(quantity="200.0")
    tracker.on_position_update(updated)

    assert tracker.securities["SPY"].position_updated_at is not None
    assert tracker.securities["SPY"].position_updated_at >= original_ts  # type: ignore[operator]


# ---------------------------------------------------------------------------
# on_greeks_event — AC1: Equity Option Greeks populated
# ---------------------------------------------------------------------------


def test_greeks_event_populates_equity_option() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_equity_option_position()])
    sec = tracker.securities[".MCD260320P305"]
    assert sec.delta is None
    assert sec.gamma is None

    tracker.on_greeks_event(make_greeks(".MCD260320P305"))
    assert sec.delta == -0.35
    assert sec.gamma == 0.04
    assert sec.theta == -0.08
    assert sec.vega == 0.15
    assert sec.rho == -0.02
    assert sec.implied_volatility == 0.28


# ---------------------------------------------------------------------------
# on_greeks_event — AC2: Future Option Greeks populated
# ---------------------------------------------------------------------------


def test_greeks_event_populates_future_option() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_future_option_position()])
    sec = tracker.securities["./EX3H26P6450:XCME"]
    assert sec.delta is None

    tracker.on_greeks_event(
        make_greeks(
            "./EX3H26P6450:XCME",
            delta=-0.22,
            gamma=0.03,
            theta=-0.05,
            vega=0.10,
            rho=-0.01,
            volatility=0.32,
        )
    )
    assert sec.delta == -0.22
    assert sec.gamma == 0.03
    assert sec.theta == -0.05
    assert sec.vega == 0.10
    assert sec.rho == -0.01
    assert sec.implied_volatility == 0.32


# ---------------------------------------------------------------------------
# on_greeks_event — AC3: Does NOT overwrite delta-1 defaults
# ---------------------------------------------------------------------------


def test_greeks_event_skips_equity_position() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])  # Equity, Long
    sec = tracker.securities["SPY"]
    assert sec.delta == 1.0
    assert sec.gamma == 0.0

    tracker.on_greeks_event(make_greeks("SPY"))
    # Equity should be unchanged — on_greeks_event skips non-option types
    assert sec.delta == 1.0
    assert sec.gamma == 0.0
    assert sec.theta == 0.0
    assert sec.vega == 0.0
    assert sec.rho == 0.0


def test_greeks_event_skips_future_position() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(
                symbol="/MESM6",
                **{
                    "instrument-type": "Future",
                    "streamer-symbol": "/MESM6",
                    "underlying-symbol": "/MESM6",
                    "multiplier": "5",
                },
            )
        ]
    )
    sec = tracker.securities["/MESM6"]
    assert sec.delta == 1.0

    tracker.on_greeks_event(make_greeks("/MESM6"))
    assert sec.delta == 1.0
    assert sec.gamma == 0.0


# ---------------------------------------------------------------------------
# on_greeks_event — AC5: greeks_updated_at timestamp
# ---------------------------------------------------------------------------


def test_greeks_event_updates_greeks_timestamp() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_equity_option_position()])
    sec = tracker.securities[".MCD260320P305"]
    assert sec.greeks_updated_at is None

    before = datetime.now()
    tracker.on_greeks_event(make_greeks(".MCD260320P305"))
    after = datetime.now()
    assert sec.greeks_updated_at is not None
    assert before <= sec.greeks_updated_at <= after


def test_greeks_event_does_not_update_timestamp_for_equity() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    sec = tracker.securities["SPY"]
    original_ts = sec.greeks_updated_at

    tracker.on_greeks_event(make_greeks("SPY"))
    assert sec.greeks_updated_at == original_ts


# ---------------------------------------------------------------------------
# on_greeks_event — edge cases
# ---------------------------------------------------------------------------


def test_greeks_event_unknown_symbol_ignored() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    tracker.on_greeks_event(make_greeks(".UNKNOWN260320P100"))
    assert len(tracker.securities) == 1


# ---------------------------------------------------------------------------
# get_streamer_symbols
# ---------------------------------------------------------------------------


def test_get_streamer_symbols_empty() -> None:
    tracker = MetricsTracker()
    assert tracker.get_streamer_symbols() == set()


def test_get_streamer_symbols_returns_loaded() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(symbol="SPY", **{"streamer-symbol": "SPY"}),
            make_position(symbol="QQQ", **{"streamer-symbol": "QQQ"}),
        ]
    )
    assert tracker.get_streamer_symbols() == {"SPY", "QQQ"}


# ---------------------------------------------------------------------------
# get_option_streamer_symbols — AC6
# ---------------------------------------------------------------------------


def test_get_option_streamer_symbols_empty() -> None:
    tracker = MetricsTracker()
    assert tracker.get_option_streamer_symbols() == set()


def test_get_option_streamer_symbols_excludes_equities() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    assert tracker.get_option_streamer_symbols() == set()


def test_get_option_streamer_symbols_returns_only_options() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(symbol="SPY", **{"streamer-symbol": "SPY"}),
            make_equity_option_position(),
            make_future_option_position(),
        ]
    )
    result = tracker.get_option_streamer_symbols()
    assert result == {".MCD260320P305", "./EX3H26P6450:XCME"}
    assert "SPY" not in result


# ---------------------------------------------------------------------------
# df property
# ---------------------------------------------------------------------------


def test_df_returns_dataframe_with_correct_columns() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    result = tracker.df
    assert isinstance(result, pd.DataFrame)
    assert "symbol" in result.columns
    assert "bid_price" in result.columns
    assert "delta" in result.columns
    assert "price_updated_at" in result.columns
    assert len(result) == 1


def test_df_empty_tracker_returns_empty_dataframe() -> None:
    tracker = MetricsTracker()
    result = tracker.df
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0
    assert "symbol" in result.columns
    assert "delta" in result.columns


def test_df_reflects_live_updates() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    tracker.on_quote_event(make_quote("SPY", bid=600.0, ask=601.0))
    result = tracker.df
    row = result.iloc[0]
    assert row["bid_price"] == 600.0
    assert row["ask_price"] == 601.0
    assert row["mid_price"] == 600.5
    assert row["delta"] == 1.0


def test_df_mixed_positions_shows_greeks_difference() -> None:
    tracker = MetricsTracker()
    tracker.load_positions(
        [
            make_position(symbol="SPY", **{"streamer-symbol": "SPY"}),
            make_position(
                symbol="MCD   260320P00305000",
                **{
                    "instrument-type": "Equity Option",
                    "streamer-symbol": ".MCD260320P305",
                    "underlying-symbol": "MCD",
                },
            ),
        ]
    )
    result = tracker.df
    spy_row = result[result["streamer_symbol"] == "SPY"].iloc[0]
    opt_row = result[result["streamer_symbol"] == ".MCD260320P305"].iloc[0]
    assert spy_row["delta"] == 1.0
    assert pd.isna(opt_row["delta"])


# ---------------------------------------------------------------------------
# MetricsEventProcessor
# ---------------------------------------------------------------------------


def test_processor_name_is_metrics() -> None:
    tracker = MetricsTracker()
    processor = MetricsEventProcessor(tracker)
    assert processor.name == "metrics"


def test_processor_routes_quote_to_tracker() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    processor = MetricsEventProcessor(tracker)
    processor.process_event(make_quote("SPY", bid=600.0, ask=601.0))
    sec = tracker.securities["SPY"]
    assert sec.bid_price == 600.0
    assert sec.ask_price == 601.0


def test_processor_routes_greeks_to_tracker() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_equity_option_position()])
    processor = MetricsEventProcessor(tracker)
    processor.process_event(make_greeks(".MCD260320P305"))
    sec = tracker.securities[".MCD260320P305"]
    assert sec.delta == -0.35
    assert sec.gamma == 0.04
    assert sec.implied_volatility == 0.28


def test_processor_ignores_other_event_types() -> None:
    tracker = MetricsTracker()
    tracker.load_positions([make_position()])
    processor = MetricsEventProcessor(tracker)
    trade = TradeEvent(eventSymbol="SPY", price=600.0, dayVolume=50000000.0)
    processor.process_event(trade)
    sec = tracker.securities["SPY"]
    assert sec.bid_price is None  # unchanged


def test_processor_close_is_noop() -> None:
    tracker = MetricsTracker()
    processor = MetricsEventProcessor(tracker)
    processor.close()  # should not raise


# ---------------------------------------------------------------------------
# Constants coverage
# ---------------------------------------------------------------------------


def test_delta_1_and_option_types_are_disjoint() -> None:
    assert DELTA_1_TYPES & OPTION_TYPES == frozenset()


def test_all_instrument_types_classified() -> None:
    all_types = set(InstrumentType)
    classified = DELTA_1_TYPES | OPTION_TYPES
    assert classified == all_types, f"Unclassified types: {all_types - classified}"
