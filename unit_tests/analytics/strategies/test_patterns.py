"""Unit tests for strategy pattern matchers."""

from datetime import date
from decimal import Decimal

from tastytrade.accounts.models import InstrumentType
from tastytrade.analytics.strategies.models import ParsedLeg, StrategyType
from tastytrade.analytics.strategies.patterns import (
    match_big_lizard,
    match_call_butterfly,
    match_call_bwb,
    match_calendar_spread,
    match_collar,
    match_covered_call,
    match_covered_jade_lizard,
    match_diagonal_spread,
    match_iron_butterfly,
    match_iron_bwb,
    match_iron_condor,
    match_jade_lizard,
    match_protective_put,
    match_put_butterfly,
    match_put_bwb,
    match_ratio_spread,
    match_single_leg,
    match_straddle,
    match_strangle,
    match_synthetic,
    match_vertical_spread,
    same_abs_quantity,
    same_expiration,
)

EXP = date(2026, 3, 20)
EXP2 = date(2026, 4, 17)


def make_option(
    option_type: str,
    strike: Decimal,
    signed_quantity: float,
    expiration: date = EXP,
    underlying: str = "SPY",
    symbol: str = "",
) -> ParsedLeg:
    """Factory for option ParsedLeg."""
    return ParsedLeg(
        streamer_symbol=f".SPY{option_type}{strike}",
        symbol=symbol or f"SPY  260320{option_type}{int(strike * 1000):08d}",
        underlying=underlying,
        instrument_type=InstrumentType.EQUITY_OPTION,
        signed_quantity=signed_quantity,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        days_to_expiration=30,
        delta=0.3 if option_type == "C" else -0.3,
        mid_price=2.50,
    )


def make_stock(
    signed_quantity: float,
    underlying: str = "SPY",
) -> ParsedLeg:
    """Factory for stock ParsedLeg."""
    return ParsedLeg(
        streamer_symbol=underlying,
        symbol=underlying,
        underlying=underlying,
        instrument_type=InstrumentType.EQUITY,
        signed_quantity=signed_quantity,
    )


# ===== Helper function tests =====


class TestHelpers:
    def test_same_expiration_true(self):
        legs = [
            make_option("C", Decimal("300"), 1),
            make_option("P", Decimal("290"), -1),
        ]
        assert same_expiration(legs) is True

    def test_same_expiration_false(self):
        legs = [
            make_option("C", Decimal("300"), 1, expiration=EXP),
            make_option("P", Decimal("290"), -1, expiration=EXP2),
        ]
        assert same_expiration(legs) is False

    def test_same_abs_quantity_true(self):
        legs = [
            make_option("C", Decimal("300"), 1),
            make_option("P", Decimal("290"), -1),
        ]
        assert same_abs_quantity(legs) is True

    def test_same_abs_quantity_false(self):
        legs = [
            make_option("C", Decimal("300"), 2),
            make_option("P", Decimal("290"), -1),
        ]
        assert same_abs_quantity(legs) is False


# ===== Iron Condor =====


class TestIronCondor:
    def test_match(self):
        legs = [
            make_option("P", Decimal("280"), 1),  # long low put
            make_option("P", Decimal("290"), -1),  # short high put
            make_option("C", Decimal("310"), -1),  # short low call
            make_option("C", Decimal("320"), 1),  # long high call
        ]
        result = match_iron_condor(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.IRON_CONDOR
        assert len(result.matched_legs) == 4

    def test_no_match_same_strikes(self):
        """Iron condor requires put strikes < call strikes."""
        legs = [
            make_option("P", Decimal("300"), 1),
            make_option("P", Decimal("310"), -1),
            make_option("C", Decimal("300"), -1),
            make_option("C", Decimal("310"), 1),
        ]
        # Puts overlap with calls, but short put at 310 >= short call at 300
        result = match_iron_condor(legs)
        assert result is None

    def test_no_match_different_quantities(self):
        legs = [
            make_option("P", Decimal("280"), 1),
            make_option("P", Decimal("290"), -2),
            make_option("C", Decimal("310"), -1),
            make_option("C", Decimal("320"), 1),
        ]
        result = match_iron_condor(legs)
        assert result is None

    def test_no_match_insufficient_legs(self):
        legs = [
            make_option("P", Decimal("280"), 1),
            make_option("P", Decimal("290"), -1),
        ]
        result = match_iron_condor(legs)
        assert result is None


# ===== Iron Butterfly =====


class TestIronButterfly:
    def test_match(self):
        legs = [
            make_option("P", Decimal("280"), 1),  # long low put
            make_option("P", Decimal("300"), -1),  # short put at center
            make_option("C", Decimal("300"), -1),  # short call at center
            make_option("C", Decimal("320"), 1),  # long high call
        ]
        result = match_iron_butterfly(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.IRON_BUTTERFLY

    def test_no_match_different_center_strikes(self):
        """Iron butterfly requires short put strike == short call strike."""
        legs = [
            make_option("P", Decimal("280"), 1),
            make_option("P", Decimal("295"), -1),
            make_option("C", Decimal("305"), -1),
            make_option("C", Decimal("320"), 1),
        ]
        result = match_iron_butterfly(legs)
        assert result is None

    def test_no_match_unequal_wings(self):
        """Iron butterfly requires equal wing widths (unequal = iron BWB)."""
        legs = [
            make_option("P", Decimal("290"), 1),  # 10-wide put wing
            make_option("P", Decimal("300"), -1),  # short put at center
            make_option("C", Decimal("300"), -1),  # short call at center
            make_option("C", Decimal("315"), 1),  # 15-wide call wing
        ]
        result = match_iron_butterfly(legs)
        assert result is None


# ===== Iron BWB =====


class TestIronBWB:
    def test_match_wider_call_wing(self):
        """Iron BWB with wider call wing."""
        legs = [
            make_option("P", Decimal("295"), 1),  # long put (5-wide)
            make_option("P", Decimal("300"), -1),  # short put at center
            make_option("C", Decimal("300"), -1),  # short call at center
            make_option("C", Decimal("308"), 1),  # long call (8-wide)
        ]
        result = match_iron_bwb(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.IRON_BWB
        assert len(result.matched_legs) == 4

    def test_match_wider_put_wing(self):
        """Iron BWB with wider put wing."""
        legs = [
            make_option("P", Decimal("285"), 1),  # long put (15-wide)
            make_option("P", Decimal("300"), -1),  # short put at center
            make_option("C", Decimal("300"), -1),  # short call at center
            make_option("C", Decimal("310"), 1),  # long call (10-wide)
        ]
        result = match_iron_bwb(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.IRON_BWB

    def test_no_match_equal_wings(self):
        """Equal wing widths = regular iron butterfly, not BWB."""
        legs = [
            make_option("P", Decimal("280"), 1),
            make_option("P", Decimal("300"), -1),
            make_option("C", Decimal("300"), -1),
            make_option("C", Decimal("320"), 1),
        ]
        result = match_iron_bwb(legs)
        assert result is None

    def test_no_match_different_center_strikes(self):
        """Iron BWB requires same center strike."""
        legs = [
            make_option("P", Decimal("280"), 1),
            make_option("P", Decimal("295"), -1),
            make_option("C", Decimal("305"), -1),
            make_option("C", Decimal("320"), 1),
        ]
        result = match_iron_bwb(legs)
        assert result is None

    def test_no_match_different_quantities(self):
        legs = [
            make_option("P", Decimal("290"), 1),
            make_option("P", Decimal("300"), -2),
            make_option("C", Decimal("300"), -1),
            make_option("C", Decimal("310"), 1),
        ]
        result = match_iron_bwb(legs)
        assert result is None


# ===== Call Butterfly =====


class TestCallButterfly:
    def test_match(self):
        legs = [
            make_option("C", Decimal("290"), 1),  # long low
            make_option("C", Decimal("300"), -2),  # short 2x middle
            make_option("C", Decimal("310"), 1),  # long high
        ]
        result = match_call_butterfly(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.CALL_BUTTERFLY
        assert len(result.matched_legs) == 3

    def test_no_match_wrong_ratio(self):
        legs = [
            make_option("C", Decimal("290"), 1),
            make_option("C", Decimal("300"), -1),
            make_option("C", Decimal("310"), 1),
        ]
        result = match_call_butterfly(legs)
        assert result is None

    def test_no_match_unequal_spacing(self):
        legs = [
            make_option("C", Decimal("290"), 1),
            make_option("C", Decimal("295"), -2),
            make_option("C", Decimal("310"), 1),
        ]
        result = match_call_butterfly(legs)
        assert result is None


# ===== Put Butterfly =====


class TestPutButterfly:
    def test_match(self):
        legs = [
            make_option("P", Decimal("290"), 1),
            make_option("P", Decimal("300"), -2),
            make_option("P", Decimal("310"), 1),
        ]
        result = match_put_butterfly(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.PUT_BUTTERFLY


# ===== Call BWB =====


class TestCallBWB:
    def test_match(self):
        """BWB: +1 C@100, -2 C@103, +1 C@105 (3-wide lower, 2-wide upper)."""
        legs = [
            make_option("C", Decimal("100"), 1),
            make_option("C", Decimal("103"), -2),
            make_option("C", Decimal("105"), 1),
        ]
        result = match_call_bwb(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.CALL_BWB
        assert len(result.matched_legs) == 3

    def test_no_match_equal_spacing(self):
        """Equal spacing = regular butterfly, not BWB."""
        legs = [
            make_option("C", Decimal("290"), 1),
            make_option("C", Decimal("300"), -2),
            make_option("C", Decimal("310"), 1),
        ]
        result = match_call_bwb(legs)
        assert result is None

    def test_no_match_wrong_ratio(self):
        legs = [
            make_option("C", Decimal("100"), 1),
            make_option("C", Decimal("103"), -1),
            make_option("C", Decimal("105"), 1),
        ]
        result = match_call_bwb(legs)
        assert result is None

    def test_no_match_puts(self):
        """Call BWB only matches calls."""
        legs = [
            make_option("P", Decimal("100"), 1),
            make_option("P", Decimal("103"), -2),
            make_option("P", Decimal("105"), 1),
        ]
        result = match_call_bwb(legs)
        assert result is None


# ===== Put BWB =====


class TestPutBWB:
    def test_match_real_world(self):
        """Real-world BWB: +1 P@111, -2 P@114, +1 P@115 (/ZBM6)."""
        legs = [
            make_option("P", Decimal("111"), 1),
            make_option("P", Decimal("114"), -2),
            make_option("P", Decimal("115"), 1),
        ]
        result = match_put_bwb(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.PUT_BWB
        assert len(result.matched_legs) == 3

    def test_match_wider_lower_wing(self):
        """BWB with wider lower wing."""
        legs = [
            make_option("P", Decimal("280"), 1),
            make_option("P", Decimal("295"), -2),
            make_option("P", Decimal("300"), 1),
        ]
        result = match_put_bwb(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.PUT_BWB

    def test_no_match_equal_spacing(self):
        """Equal spacing = regular butterfly, not BWB."""
        legs = [
            make_option("P", Decimal("290"), 1),
            make_option("P", Decimal("300"), -2),
            make_option("P", Decimal("310"), 1),
        ]
        result = match_put_bwb(legs)
        assert result is None

    def test_no_match_wrong_direction(self):
        """Wrong direction: sell low, buy middle, sell high."""
        legs = [
            make_option("P", Decimal("111"), -1),
            make_option("P", Decimal("114"), 2),
            make_option("P", Decimal("115"), -1),
        ]
        result = match_put_bwb(legs)
        assert result is None

    def test_no_match_calls(self):
        """Put BWB only matches puts."""
        legs = [
            make_option("C", Decimal("111"), 1),
            make_option("C", Decimal("114"), -2),
            make_option("C", Decimal("115"), 1),
        ]
        result = match_put_bwb(legs)
        assert result is None


# ===== Jade Lizard =====


class TestJadeLizard:
    def test_match(self):
        legs = [
            make_option("P", Decimal("280"), -1),  # short OTM put
            make_option("C", Decimal("310"), -1),  # short call
            make_option("C", Decimal("320"), 1),  # long higher call
        ]
        result = match_jade_lizard(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.JADE_LIZARD
        assert len(result.matched_legs) == 3

    def test_variant_b_short_call_plus_bull_put_spread(self):
        """Variant B: short call + bull put spread (short put + long lower put)."""
        legs = [
            make_option("C", Decimal("320"), -1),  # short OTM call
            make_option("P", Decimal("290"), -1),  # short put (higher strike)
            make_option("P", Decimal("280"), 1),  # long put (lower strike)
        ]
        result = match_jade_lizard(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.JADE_LIZARD
        assert len(result.matched_legs) == 3

    def test_no_match_wrong_call_direction(self):
        legs = [
            make_option("P", Decimal("280"), -1),
            make_option("C", Decimal("310"), 1),  # wrong: long lower call
            make_option("C", Decimal("320"), -1),  # wrong: short higher call
        ]
        result = match_jade_lizard(legs)
        assert result is None

    def test_no_match_variant_b_wrong_put_direction(self):
        """Variant B fails when put spread direction is inverted."""
        legs = [
            make_option("C", Decimal("320"), -1),  # short call
            make_option("P", Decimal("290"), 1),  # wrong: long higher put
            make_option("P", Decimal("280"), -1),  # wrong: short lower put
        ]
        result = match_jade_lizard(legs)
        assert result is None


# ===== Covered Jade Lizard =====


class TestCoveredJadeLizard:
    def test_match(self):
        legs = [
            make_stock(100),  # long stock
            make_option("P", Decimal("280"), -1),  # short put
            make_option("C", Decimal("310"), -1),  # short lower call
            make_option("C", Decimal("320"), 1),  # long higher call
        ]
        result = match_covered_jade_lizard(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.COVERED_JADE_LIZARD
        assert len(result.matched_legs) == 4


# ===== Big Lizard =====


class TestBigLizard:
    def test_match(self):
        legs = [
            make_option("P", Decimal("300"), -1),  # short put at 300
            make_option("C", Decimal("300"), -1),  # short call at 300
            make_option("C", Decimal("320"), 1),  # long call at 320
        ]
        result = match_big_lizard(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.BIG_LIZARD

    def test_no_match_straddle_strikes_differ(self):
        legs = [
            make_option("P", Decimal("295"), -1),
            make_option("C", Decimal("300"), -1),
            make_option("C", Decimal("320"), 1),
        ]
        result = match_big_lizard(legs)
        assert result is None


# ===== Collar =====


class TestCollar:
    def test_match(self):
        legs = [
            make_stock(100),
            make_option("P", Decimal("280"), 1),  # long put
            make_option("C", Decimal("310"), -1),  # short call
        ]
        result = match_collar(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.COLLAR
        assert len(result.matched_legs) == 3


# ===== Covered Call =====


class TestCoveredCall:
    def test_match(self):
        legs = [
            make_stock(100),
            make_option("C", Decimal("310"), -1),
        ]
        result = match_covered_call(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.COVERED_CALL

    def test_no_match_long_call(self):
        legs = [
            make_stock(100),
            make_option("C", Decimal("310"), 1),
        ]
        result = match_covered_call(legs)
        assert result is None


# ===== Protective Put =====


class TestProtectivePut:
    def test_match(self):
        legs = [
            make_stock(100),
            make_option("P", Decimal("280"), 1),
        ]
        result = match_protective_put(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.PROTECTIVE_PUT


# ===== Vertical Spreads =====


class TestVerticalSpread:
    def test_bull_call_spread(self):
        legs = [
            make_option("C", Decimal("300"), 1),  # long lower call
            make_option("C", Decimal("310"), -1),  # short higher call
        ]
        result = match_vertical_spread(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.BULL_CALL_SPREAD

    def test_bear_call_spread(self):
        legs = [
            make_option("C", Decimal("300"), -1),  # short lower call
            make_option("C", Decimal("310"), 1),  # long higher call
        ]
        result = match_vertical_spread(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.BEAR_CALL_SPREAD

    def test_bull_put_spread(self):
        legs = [
            make_option("P", Decimal("280"), -1),  # short lower put
            make_option("P", Decimal("290"), 1),  # long higher put
        ]
        result = match_vertical_spread(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.BULL_PUT_SPREAD

    def test_bear_put_spread(self):
        legs = [
            make_option("P", Decimal("280"), 1),  # long lower put
            make_option("P", Decimal("290"), -1),  # short higher put
        ]
        result = match_vertical_spread(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.BEAR_PUT_SPREAD

    def test_no_match_different_expirations(self):
        legs = [
            make_option("C", Decimal("300"), 1, expiration=EXP),
            make_option("C", Decimal("310"), -1, expiration=EXP2),
        ]
        result = match_vertical_spread(legs)
        assert result is None

    def test_no_match_same_strike(self):
        legs = [
            make_option("C", Decimal("300"), 1),
            make_option("C", Decimal("300"), -1),
        ]
        result = match_vertical_spread(legs)
        assert result is None


# ===== Ratio Spread =====


class TestRatioSpread:
    def test_match(self):
        legs = [
            make_option("C", Decimal("300"), 1),  # 1x long
            make_option("C", Decimal("310"), -2),  # 2x short
        ]
        result = match_ratio_spread(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.RATIO_SPREAD

    def test_no_match_same_quantity(self):
        """Same quantity = vertical spread, not ratio."""
        legs = [
            make_option("C", Decimal("300"), 1),
            make_option("C", Decimal("310"), -1),
        ]
        result = match_ratio_spread(legs)
        assert result is None


# ===== Straddle =====


class TestStraddle:
    def test_short_straddle(self):
        legs = [
            make_option("C", Decimal("300"), -1),
            make_option("P", Decimal("300"), -1),
        ]
        result = match_straddle(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.SHORT_STRADDLE

    def test_long_straddle(self):
        legs = [
            make_option("C", Decimal("300"), 1),
            make_option("P", Decimal("300"), 1),
        ]
        result = match_straddle(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.LONG_STRADDLE

    def test_no_match_different_strikes(self):
        legs = [
            make_option("C", Decimal("305"), -1),
            make_option("P", Decimal("300"), -1),
        ]
        result = match_straddle(legs)
        assert result is None


# ===== Strangle =====


class TestStrangle:
    def test_short_strangle(self):
        legs = [
            make_option("C", Decimal("310"), -1),
            make_option("P", Decimal("290"), -1),
        ]
        result = match_strangle(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.SHORT_STRANGLE

    def test_long_strangle(self):
        legs = [
            make_option("C", Decimal("310"), 1),
            make_option("P", Decimal("290"), 1),
        ]
        result = match_strangle(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.LONG_STRANGLE

    def test_no_match_same_strike(self):
        """Same strike = straddle, not strangle."""
        legs = [
            make_option("C", Decimal("300"), -1),
            make_option("P", Decimal("300"), -1),
        ]
        result = match_strangle(legs)
        assert result is None

    def test_no_match_opposite_directions(self):
        legs = [
            make_option("C", Decimal("310"), 1),
            make_option("P", Decimal("290"), -1),
        ]
        result = match_strangle(legs)
        assert result is None


# ===== Synthetic =====


class TestSynthetic:
    def test_synthetic_long(self):
        legs = [
            make_option("C", Decimal("300"), 1),  # long call
            make_option("P", Decimal("300"), -1),  # short put
        ]
        result = match_synthetic(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.SYNTHETIC_LONG

    def test_synthetic_short(self):
        legs = [
            make_option("C", Decimal("300"), -1),  # short call
            make_option("P", Decimal("300"), 1),  # long put
        ]
        result = match_synthetic(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.SYNTHETIC_SHORT


# ===== Calendar Spread =====


class TestCalendarSpread:
    def test_match(self):
        legs = [
            make_option("C", Decimal("300"), -1, expiration=EXP),
            make_option("C", Decimal("300"), 1, expiration=EXP2),
        ]
        result = match_calendar_spread(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.CALENDAR_SPREAD

    def test_no_match_different_strikes(self):
        legs = [
            make_option("C", Decimal("300"), -1, expiration=EXP),
            make_option("C", Decimal("310"), 1, expiration=EXP2),
        ]
        result = match_calendar_spread(legs)
        assert result is None

    def test_no_match_same_expiration(self):
        legs = [
            make_option("C", Decimal("300"), -1, expiration=EXP),
            make_option("C", Decimal("300"), 1, expiration=EXP),
        ]
        result = match_calendar_spread(legs)
        assert result is None


# ===== Diagonal Spread =====


class TestDiagonalSpread:
    def test_match(self):
        legs = [
            make_option("C", Decimal("300"), -1, expiration=EXP),
            make_option("C", Decimal("310"), 1, expiration=EXP2),
        ]
        result = match_diagonal_spread(legs)
        assert result is not None
        assert result.strategy_type == StrategyType.DIAGONAL_SPREAD


# ===== Single Leg =====


class TestSingleLeg:
    def test_long_stock(self):
        leg = make_stock(100)
        assert match_single_leg(leg) == StrategyType.LONG_STOCK

    def test_short_stock(self):
        leg = make_stock(-100)
        assert match_single_leg(leg) == StrategyType.SHORT_STOCK

    def test_long_call(self):
        leg = make_option("C", Decimal("300"), 1)
        assert match_single_leg(leg) == StrategyType.LONG_CALL

    def test_naked_call(self):
        leg = make_option("C", Decimal("300"), -1)
        assert match_single_leg(leg) == StrategyType.NAKED_CALL

    def test_long_put(self):
        leg = make_option("P", Decimal("300"), 1)
        assert match_single_leg(leg) == StrategyType.LONG_PUT

    def test_naked_put(self):
        leg = make_option("P", Decimal("300"), -1)
        assert match_single_leg(leg) == StrategyType.NAKED_PUT

    def test_long_future(self):
        leg = ParsedLeg(
            streamer_symbol="/ES",
            symbol="/ES",
            underlying="/ES",
            instrument_type=InstrumentType.FUTURE,
            signed_quantity=1,
        )
        assert match_single_leg(leg) == StrategyType.LONG_FUTURE

    def test_short_crypto(self):
        leg = ParsedLeg(
            streamer_symbol="BTC/USD",
            symbol="BTC/USD",
            underlying="BTC/USD",
            instrument_type=InstrumentType.CRYPTOCURRENCY,
            signed_quantity=-1,
        )
        assert match_single_leg(leg) == StrategyType.SHORT_CRYPTO
