"""Unit tests for Strategy model P&L calculations with entry_value."""

from decimal import Decimal

from tastytrade.accounts.models import InstrumentType
from tastytrade.analytics.strategies.models import (
    ParsedLeg,
    Strategy,
    StrategyType,
    compute_net_entry_credit_dollars,
)


def make_option_leg(
    option_type: str,
    strike: Decimal,
    signed_quantity: float,
    entry_value: Decimal | None = None,
    multiplier: Decimal = Decimal("100"),
    instrument_type: InstrumentType = InstrumentType.EQUITY_OPTION,
) -> ParsedLeg:
    """Create a ParsedLeg for strategy model tests.

    entry_value follows LIFO convention: positive = credit received (STO),
    negative = debit paid (BTO). The sign is baked in by the LIFO replay.
    """
    return ParsedLeg(
        streamer_symbol=f".TEST{option_type}{strike}",
        symbol=f"TEST {option_type}{strike}",
        underlying="TEST",
        instrument_type=instrument_type,
        signed_quantity=signed_quantity,
        option_type=option_type,
        strike=strike,
        expiration=None,
        days_to_expiration=30,
        multiplier=multiplier,
        entry_value=entry_value,
    )


class TestNetEntryCredit:
    """Test compute_net_entry_credit_dollars.

    entry_value is already signed by LIFO: positive=credit, negative=debit.
    Net credit = sum of all entry_values.
    """

    def test_credit_spread(self) -> None:
        """Short leg credit + long leg debit → positive net credit."""
        legs = [
            # Sold P@250 for $300 credit
            make_option_leg("P", Decimal("250"), -1, entry_value=Decimal("300")),
            # Bought P@245 for $150 debit
            make_option_leg("P", Decimal("245"), 1, entry_value=Decimal("-150")),
        ]
        result = compute_net_entry_credit_dollars(legs)
        assert result == Decimal("150")

    def test_debit_spread(self) -> None:
        """Long leg debit > short leg credit → negative net credit."""
        legs = [
            # Bought C@260 for $500 debit
            make_option_leg("C", Decimal("260"), 1, entry_value=Decimal("-500")),
            # Sold C@270 for $200 credit
            make_option_leg("C", Decimal("270"), -1, entry_value=Decimal("200")),
        ]
        result = compute_net_entry_credit_dollars(legs)
        assert result == Decimal("-300")

    def test_missing_entry_value_returns_none(self) -> None:
        legs = [
            make_option_leg("P", Decimal("250"), -1, entry_value=Decimal("300")),
            make_option_leg("P", Decimal("245"), 1, entry_value=None),
        ]
        assert compute_net_entry_credit_dollars(legs) is None


class TestMaxProfit:
    """Test compute_max_profit for various strategy types."""

    def test_bear_call_spread_credit(self) -> None:
        """Bear call spread: max profit = net credit received."""
        legs = (
            # Sold C@250 for $400 credit
            make_option_leg("C", Decimal("250"), -1, entry_value=Decimal("400")),
            # Bought C@260 for $150 debit
            make_option_leg("C", Decimal("260"), 1, entry_value=Decimal("-150")),
        )
        strat = Strategy(
            strategy_type=StrategyType.BEAR_CALL_SPREAD,
            underlying="SPY",
            legs=legs,
        )
        # Net credit = 400 + (-150) = 250
        assert strat.max_profit == Decimal("250")

    def test_bull_call_spread_debit(self) -> None:
        """Bull call spread: max profit = width × multiplier - net debit."""
        legs = (
            # Bought C@250 for $500 debit
            make_option_leg("C", Decimal("250"), 1, entry_value=Decimal("-500")),
            # Sold C@260 for $200 credit
            make_option_leg("C", Decimal("260"), -1, entry_value=Decimal("200")),
        )
        strat = Strategy(
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            underlying="SPY",
            legs=legs,
        )
        # Width = 10, multiplier = 100, net_credit = -300 (debit)
        # Max profit = 10 * 100 + (-300) = 700
        assert strat.max_profit == Decimal("700")

    def test_iron_condor_credit(self) -> None:
        """Iron condor: max profit = net credit."""
        legs = (
            # Bought P@240 for $50 debit
            make_option_leg("P", Decimal("240"), 1, entry_value=Decimal("-50")),
            # Sold P@245 for $100 credit
            make_option_leg("P", Decimal("245"), -1, entry_value=Decimal("100")),
            # Sold C@260 for $120 credit
            make_option_leg("C", Decimal("260"), -1, entry_value=Decimal("120")),
            # Bought C@265 for $40 debit
            make_option_leg("C", Decimal("265"), 1, entry_value=Decimal("-40")),
        )
        strat = Strategy(
            strategy_type=StrategyType.IRON_CONDOR,
            underlying="SPY",
            legs=legs,
        )
        # Net credit = -50 + 100 + 120 + (-40) = 130
        assert strat.max_profit == Decimal("130")

    def test_missing_entry_value_returns_none(self) -> None:
        legs = (
            make_option_leg("C", Decimal("250"), -1, entry_value=None),
            make_option_leg("C", Decimal("260"), 1, entry_value=Decimal("-150")),
        )
        strat = Strategy(
            strategy_type=StrategyType.BEAR_CALL_SPREAD,
            underlying="SPY",
            legs=legs,
        )
        assert strat.max_profit is None


class TestMaxLoss:
    """Test compute_max_loss for various strategy types."""

    def test_bear_call_spread(self) -> None:
        """Credit spread: max loss = width × multiplier - net credit."""
        legs = (
            make_option_leg("C", Decimal("250"), -1, entry_value=Decimal("400")),
            make_option_leg("C", Decimal("260"), 1, entry_value=Decimal("-150")),
        )
        strat = Strategy(
            strategy_type=StrategyType.BEAR_CALL_SPREAD,
            underlying="SPY",
            legs=legs,
        )
        # Width=10, mult=100, net_credit=250
        # Max loss = 10*100 - 250 = 750
        assert strat.max_loss == Decimal("750")

    def test_bull_call_spread(self) -> None:
        """Debit spread: max loss = net debit paid."""
        legs = (
            make_option_leg("C", Decimal("250"), 1, entry_value=Decimal("-500")),
            make_option_leg("C", Decimal("260"), -1, entry_value=Decimal("200")),
        )
        strat = Strategy(
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            underlying="SPY",
            legs=legs,
        )
        # Net credit = -300 → debit = 300
        assert strat.max_loss == Decimal("300")

    def test_iron_condor(self) -> None:
        """Iron condor: max loss = wider wing × multiplier - net credit."""
        legs = (
            make_option_leg("P", Decimal("240"), 1, entry_value=Decimal("-50")),
            make_option_leg("P", Decimal("245"), -1, entry_value=Decimal("100")),
            make_option_leg("C", Decimal("260"), -1, entry_value=Decimal("120")),
            make_option_leg("C", Decimal("265"), 1, entry_value=Decimal("-40")),
        )
        strat = Strategy(
            strategy_type=StrategyType.IRON_CONDOR,
            underlying="SPY",
            legs=legs,
        )
        # Put width=5, Call width=5, wing_width=5, mult=100, net_credit=130
        # Max loss = 5*100 - 130 = 370
        assert strat.max_loss == Decimal("370")

    def test_naked_call_unlimited(self) -> None:
        """Naked call: max loss is unlimited → None."""
        legs = (make_option_leg("C", Decimal("260"), -1, entry_value=Decimal("300")),)
        strat = Strategy(
            strategy_type=StrategyType.NAKED_CALL,
            underlying="SPY",
            legs=legs,
        )
        assert strat.max_loss is None

    def test_short_strangle_unlimited(self) -> None:
        """Short strangle: max loss is unlimited → None."""
        legs = (
            make_option_leg("P", Decimal("240"), -1, entry_value=Decimal("200")),
            make_option_leg("C", Decimal("260"), -1, entry_value=Decimal("200")),
        )
        strat = Strategy(
            strategy_type=StrategyType.SHORT_STRANGLE,
            underlying="SPY",
            legs=legs,
        )
        assert strat.max_loss is None

    def test_futures_option_multiplier(self) -> None:
        """Future option spread uses the future's notional multiplier."""
        legs = (
            # Sold P@1.05 for $625 credit
            make_option_leg(
                "P",
                Decimal("1.05"),
                -1,
                entry_value=Decimal("625"),
                multiplier=Decimal("125000"),
                instrument_type=InstrumentType.FUTURE_OPTION,
            ),
            # Bought P@1.04 for $500 debit
            make_option_leg(
                "P",
                Decimal("1.04"),
                1,
                entry_value=Decimal("-500"),
                multiplier=Decimal("125000"),
                instrument_type=InstrumentType.FUTURE_OPTION,
            ),
        )
        strat = Strategy(
            strategy_type=StrategyType.BULL_PUT_SPREAD,
            underlying="/6E",
            legs=legs,
        )
        # Width=0.01, mult=125000, net_credit=625+(-500)=125
        # Max loss = 0.01*125000 - 125 = 1250 - 125 = 1125
        assert strat.max_loss == Decimal("1125")
        # Max profit = net credit = 125
        assert strat.max_profit == Decimal("125")


class TestButterflyMaxProfitLoss:
    """Test max profit/loss for butterfly and broken fly strategies."""

    def test_balanced_put_butterfly_debit(self) -> None:
        """Balanced butterfly (debit): max profit = width*mult - debit, max loss = debit."""
        legs = (
            # +P@240 for $100 debit
            make_option_leg("P", Decimal("240"), 1, entry_value=Decimal("-100")),
            # -2P@245 for $350 credit (each)
            make_option_leg("P", Decimal("245"), -2, entry_value=Decimal("350")),
            # +P@250 for $400 debit
            make_option_leg("P", Decimal("250"), 1, entry_value=Decimal("-400")),
        )
        strat = Strategy(
            strategy_type=StrategyType.PUT_BUTTERFLY,
            underlying="SPY",
            legs=legs,
        )
        # Net credit = -100 + 350 + (-400) = -150 (net debit of $150)
        # Narrow width = 5 (both wings equal), mult = 100
        # Max profit = 5 * 100 + (-150) = 350
        assert strat.max_profit == Decimal("350")
        # Max loss = max(-(-150), 0*100 - (-150), 0) = max(150, 150, 0) = 150
        assert strat.max_loss == Decimal("150")

    def test_broken_fly_credit(self) -> None:
        """Broken wing butterfly (credit): wide wing has more risk."""
        legs = (
            # +P@111 for $281 debit
            make_option_leg("P", Decimal("111"), 1, entry_value=Decimal("-281")),
            # -2P@114 for $734 credit (each, total $1468)
            make_option_leg("P", Decimal("114"), -2, entry_value=Decimal("1468")),
            # +P@115 for $1031 debit
            make_option_leg("P", Decimal("115"), 1, entry_value=Decimal("-1031")),
        )
        strat = Strategy(
            strategy_type=StrategyType.BROKEN_FLY,
            underlying="/ZB",
            legs=legs,
        )
        # Net credit = -281 + 1468 + (-1031) = 156
        # Narrow width = 1 (115-114), wide width = 3 (114-111), mult = 100
        # Max profit = 1 * 100 + 156 = 256
        assert strat.max_profit == Decimal("256")
        # Max loss: downside = (3-1)*100 - 156 = 44, upside = -156 (negative)
        # max(44, -156, 0) = 44
        assert strat.max_loss == Decimal("44")

    def test_broken_fly_futures_multiplier(self) -> None:
        """Broken fly with futures multiplier ($1000 per point for /ZB)."""
        legs = (
            make_option_leg(
                "P",
                Decimal("111"),
                1,
                entry_value=Decimal("-281"),
                multiplier=Decimal("1000"),
                instrument_type=InstrumentType.FUTURE_OPTION,
            ),
            make_option_leg(
                "P",
                Decimal("114"),
                -2,
                entry_value=Decimal("1468"),
                multiplier=Decimal("1000"),
                instrument_type=InstrumentType.FUTURE_OPTION,
            ),
            make_option_leg(
                "P",
                Decimal("115"),
                1,
                entry_value=Decimal("-1031"),
                multiplier=Decimal("1000"),
                instrument_type=InstrumentType.FUTURE_OPTION,
            ),
        )
        strat = Strategy(
            strategy_type=StrategyType.BROKEN_FLY,
            underlying="/ZB",
            legs=legs,
        )
        # Net credit = 156, narrow_width = 1, wide_width = 3, mult = 1000
        # Max profit = 1 * 1000 + 156 = 1156
        assert strat.max_profit == Decimal("1156")
        # Max loss: downside = (3-1)*1000 - 156 = 1844, upside = -156
        # max(1844, -156, 0) = 1844
        assert strat.max_loss == Decimal("1844")

    def test_missing_entry_value_returns_none(self) -> None:
        """Butterfly with missing entry value → None."""
        legs = (
            make_option_leg("P", Decimal("240"), 1, entry_value=None),
            make_option_leg("P", Decimal("245"), -2, entry_value=Decimal("350")),
            make_option_leg("P", Decimal("250"), 1, entry_value=Decimal("-400")),
        )
        strat = Strategy(
            strategy_type=StrategyType.BROKEN_FLY,
            underlying="SPY",
            legs=legs,
        )
        assert strat.max_profit is None
        assert strat.max_loss is None
