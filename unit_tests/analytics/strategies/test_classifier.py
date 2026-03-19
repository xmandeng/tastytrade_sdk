"""Unit tests for StrategyClassifier end-to-end greedy matching."""

import json
from datetime import date
from decimal import Decimal

from tastytrade.accounts.models import InstrumentType, QuantityDirection
from tastytrade.analytics.metrics import SecurityMetrics
from tastytrade.analytics.strategies.classifier import StrategyClassifier
from tastytrade.analytics.strategies.models import StrategyType


def make_security(
    symbol: str,
    streamer_symbol: str,
    underlying_symbol: str,
    instrument_type: InstrumentType,
    quantity: float,
    quantity_direction: QuantityDirection,
    delta: float | None = None,
    mid_price: float | None = None,
) -> SecurityMetrics:
    """Create a SecurityMetrics object for testing."""
    sec = SecurityMetrics(
        symbol=symbol,
        streamer_symbol=streamer_symbol,
        underlying_symbol=underlying_symbol,
        instrument_type=instrument_type,
        quantity=quantity,
        quantity_direction=quantity_direction,
    )
    sec.delta = delta
    sec.mid_price = mid_price
    return sec


def make_instrument_json(
    option_type: str = "C",
    strike_price: float = 300.0,
    expiration_date: str = "2026-03-20",
    days_to_expiration: int = 30,
) -> dict:
    """Create instrument dict as stored in Redis."""
    return {
        "option-type": option_type,
        "strike-price": strike_price,
        "expiration-date": expiration_date,
        "days-to-expiration": days_to_expiration,
    }


class TestBuildParsedLeg:
    def test_option_with_instrument(self):
        sec = make_security(
            symbol="SPY  260320C00300000",
            streamer_symbol=".SPY260320C300",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
            delta=-0.3,
            mid_price=5.50,
        )
        instruments = {
            "SPY  260320C00300000": make_instrument_json("C", 300.0, "2026-03-20", 30),
        }

        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, instruments)

        assert leg.symbol == "SPY  260320C00300000"
        assert leg.underlying == "SPY"
        assert leg.option_type == "C"
        assert leg.strike == Decimal("300.0")
        assert leg.expiration == date(2026, 3, 20)
        assert leg.days_to_expiration == 30
        assert leg.signed_quantity == -1  # Short → negative
        assert leg.delta == -0.3
        assert leg.mid_price == 5.50

    def test_stock_without_instrument(self):
        sec = make_security(
            symbol="SPY",
            streamer_symbol="SPY",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY,
            quantity=100,
            quantity_direction=QuantityDirection.LONG,
        )
        instruments = {}

        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, instruments)

        assert leg.signed_quantity == 100
        assert leg.option_type is None
        assert leg.strike is None
        assert leg.is_stock is True

    def test_long_direction_positive(self):
        sec = make_security(
            symbol="SPY  260320C00300000",
            streamer_symbol=".SPY260320C300",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=2,
            quantity_direction=QuantityDirection.LONG,
        )
        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, {})
        assert leg.signed_quantity == 2

    def test_instrument_json_string(self):
        """Instrument data may arrive as a JSON string (from Redis bytes)."""
        sec = make_security(
            symbol="SPY  260320P00290000",
            streamer_symbol=".SPY260320P290",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
        )
        instruments = {
            "SPY  260320P00290000": json.dumps(
                make_instrument_json("P", 290.0, "2026-03-20", 30)
            ),
        }

        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, instruments)

        assert leg.option_type == "P"
        assert leg.strike == Decimal("290.0")


class TestClassifyGreedy:
    """Test end-to-end greedy classification."""

    def test_iron_condor(self):
        """4 options on same underlying → iron condor."""
        securities = {}
        instruments = {}

        legs_data = [
            ("P280", "P", 280, QuantityDirection.LONG),
            ("P290", "P", 290, QuantityDirection.SHORT),
            ("C310", "C", 310, QuantityDirection.SHORT),
            ("C320", "C", 320, QuantityDirection.LONG),
        ]
        for suffix, opt_type, strike, direction in legs_data:
            sym = f"SPY  {suffix}"
            sec = make_security(
                symbol=sym,
                streamer_symbol=f".SPY{suffix}",
                underlying_symbol="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                quantity=1,
                quantity_direction=direction,
                delta=0.1,
                mid_price=2.0,
            )
            securities[sec.streamer_symbol] = sec
            instruments[sym] = make_instrument_json(opt_type, strike)

        classifier = StrategyClassifier()
        strategies = classifier.classify(securities, instruments)

        assert len(strategies) == 1
        assert strategies[0].strategy_type == StrategyType.IRON_CONDOR
        assert strategies[0].underlying == "SPY"

    def test_short_strangle(self):
        """Short call + short put at different strikes → short strangle."""
        securities = {}
        instruments = {}

        sym_call = "SPY  260320C00310000"
        sec_call = make_security(
            symbol=sym_call,
            streamer_symbol=".SPYC310",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
            delta=-0.2,
            mid_price=3.0,
        )
        securities[sec_call.streamer_symbol] = sec_call
        instruments[sym_call] = make_instrument_json("C", 310.0)

        sym_put = "SPY  260320P00290000"
        sec_put = make_security(
            symbol=sym_put,
            streamer_symbol=".SPYP290",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
            delta=-0.3,
            mid_price=2.5,
        )
        securities[sec_put.streamer_symbol] = sec_put
        instruments[sym_put] = make_instrument_json("P", 290.0)

        classifier = StrategyClassifier()
        strategies = classifier.classify(securities, instruments)

        assert len(strategies) == 1
        assert strategies[0].strategy_type == StrategyType.SHORT_STRANGLE

    def test_covered_call(self):
        """Long stock + short call → covered call."""
        securities = {}
        instruments = {}

        sec_stock = make_security(
            symbol="SPY",
            streamer_symbol="SPY",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY,
            quantity=100,
            quantity_direction=QuantityDirection.LONG,
        )
        securities[sec_stock.streamer_symbol] = sec_stock

        sym_call = "SPY  260320C00310000"
        sec_call = make_security(
            symbol=sym_call,
            streamer_symbol=".SPYC310",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
            delta=-0.3,
            mid_price=2.5,
        )
        securities[sec_call.streamer_symbol] = sec_call
        instruments[sym_call] = make_instrument_json("C", 310.0)

        classifier = StrategyClassifier()
        strategies = classifier.classify(securities, instruments)

        assert len(strategies) == 1
        assert strategies[0].strategy_type == StrategyType.COVERED_CALL

    def test_multiple_underlyings_separate(self):
        """Positions on different underlyings classify independently."""
        securities = {}
        instruments = {}

        # SPY: single naked put
        sym_spy = "SPY  260320P00290000"
        sec_spy = make_security(
            symbol=sym_spy,
            streamer_symbol=".SPYP290",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
        )
        securities[sec_spy.streamer_symbol] = sec_spy
        instruments[sym_spy] = make_instrument_json("P", 290.0)

        # AAPL: single naked call
        sym_aapl = "AAPL 260320C00200000"
        sec_aapl = make_security(
            symbol=sym_aapl,
            streamer_symbol=".AAPLC200",
            underlying_symbol="AAPL",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
        )
        securities[sec_aapl.streamer_symbol] = sec_aapl
        instruments[sym_aapl] = make_instrument_json("C", 200.0)

        classifier = StrategyClassifier()
        strategies = classifier.classify(securities, instruments)

        assert len(strategies) == 2
        types = {s.strategy_type for s in strategies}
        underlyings = {s.underlying for s in strategies}
        assert StrategyType.NAKED_PUT in types
        assert StrategyType.NAKED_CALL in types
        assert underlyings == {"SPY", "AAPL"}

    def test_greedy_consumes_legs(self):
        """3 short puts + 1 short call → 1 strangle + 2 naked puts.

        Greedy matcher should match strangle first (1 put + 1 call),
        leaving 2 unmatched puts as single-leg strategies.
        """
        securities = {}
        instruments = {}

        # 3 short puts at different strikes
        for strike in [280, 285, 290]:
            sym = f"SPY  260320P00{strike}000"
            sec = make_security(
                symbol=sym,
                streamer_symbol=f".SPYP{strike}",
                underlying_symbol="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                quantity=1,
                quantity_direction=QuantityDirection.SHORT,
            )
            securities[sec.streamer_symbol] = sec
            instruments[sym] = make_instrument_json("P", float(strike))

        # 1 short call
        sym_call = "SPY  260320C00310000"
        sec_call = make_security(
            symbol=sym_call,
            streamer_symbol=".SPYC310",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
        )
        securities[sec_call.streamer_symbol] = sec_call
        instruments[sym_call] = make_instrument_json("C", 310.0)

        classifier = StrategyClassifier()
        strategies = classifier.classify(securities, instruments)

        strangles = [
            s for s in strategies if s.strategy_type == StrategyType.SHORT_STRANGLE
        ]
        naked_puts = [
            s for s in strategies if s.strategy_type == StrategyType.NAKED_PUT
        ]

        assert len(strangles) == 1
        assert len(naked_puts) == 2

    def test_single_stock(self):
        """Single stock position → Long Stock."""
        securities = {}
        sec = make_security(
            symbol="AAPL",
            streamer_symbol="AAPL",
            underlying_symbol="AAPL",
            instrument_type=InstrumentType.EQUITY,
            quantity=100,
            quantity_direction=QuantityDirection.LONG,
        )
        securities[sec.streamer_symbol] = sec

        classifier = StrategyClassifier()
        strategies = classifier.classify(securities, {})

        assert len(strategies) == 1
        assert strategies[0].strategy_type == StrategyType.LONG_STOCK

    def test_empty_positions(self):
        """Empty input → empty output."""
        classifier = StrategyClassifier()
        strategies = classifier.classify({}, {})
        assert strategies == []


class TestBuildParsedLegFutureOptions:
    """Test future option price handling in build_parsed_leg."""

    def test_zero_average_open_price_becomes_none(self):
        """API returning 0.0 for average-open-price is treated as missing."""
        sec = make_security(
            symbol="./6EM6 EUUJ6 260403P1.16",
            streamer_symbol="./EUUJ26P1.16:XCME",
            underlying_symbol="/6EM6",
            instrument_type=InstrumentType.FUTURE_OPTION,
            quantity=2,
            quantity_direction=QuantityDirection.SHORT,
        )
        sec.average_open_price = 0.0
        sec.multiplier = 125000.0
        instruments = {
            "./6EM6 EUUJ6 260403P1.16": {
                "option-type": "P",
                "strike-price": "1.16",
                "expiration-date": "2026-04-03",
                "days-to-expiration": 33,
            },
        }
        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, instruments)
        assert leg.average_open_price is None

    def test_nonzero_price_preserved(self):
        """Non-zero average-open-price passes through as-is."""
        sec = make_security(
            symbol="./ZBM6 OZBJ6 260327P115",
            streamer_symbol="./OZBJ26P115:XCBT",
            underlying_symbol="/ZBM6",
            instrument_type=InstrumentType.FUTURE_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
        )
        sec.average_open_price = 0.23
        sec.multiplier = 1000.0
        instruments = {
            "./ZBM6 OZBJ6 260327P115": {
                "option-type": "P",
                "strike-price": "115.0",
                "expiration-date": "2026-03-27",
                "days-to-expiration": 26,
            },
        }
        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, instruments)
        assert leg.average_open_price == 0.23
        assert leg.multiplier == Decimal("1000.0")

    def test_entry_value_from_credits(self):
        """entry_value is populated from entry_credits dict when provided."""
        sec = make_security(
            symbol="SPY   260320P00500000",
            streamer_symbol=".SPY260320P500",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=2,
            quantity_direction=QuantityDirection.SHORT,
        )
        instruments = {
            "SPY   260320P00500000": {
                "option-type": "P",
                "strike-price": "500.0",
                "expiration-date": "2026-03-20",
                "days-to-expiration": 30,
                "shares-per-contract": 100,
            }
        }
        entry_credits = {"SPY   260320P00500000": Decimal("350.00")}
        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, instruments, entry_credits)
        assert leg.entry_value == Decimal("350.00")

    def test_entry_value_none_without_credits(self):
        """entry_value is None when no entry_credits provided."""
        sec = make_security(
            symbol="SPY   260320P00500000",
            streamer_symbol=".SPY260320P500",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.SHORT,
        )
        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, {})
        assert leg.entry_value is None

    def test_entry_value_none_when_symbol_missing(self):
        """entry_value is None when symbol not in entry_credits map."""
        sec = make_security(
            symbol="SPY   260320C00550000",
            streamer_symbol=".SPY260320C550",
            underlying_symbol="SPY",
            instrument_type=InstrumentType.EQUITY_OPTION,
            quantity=1,
            quantity_direction=QuantityDirection.LONG,
        )
        entry_credits = {"OTHER_SYMBOL": Decimal("100.00")}
        classifier = StrategyClassifier()
        leg = classifier.build_parsed_leg(sec, {}, entry_credits)
        assert leg.entry_value is None
