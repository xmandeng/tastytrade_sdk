"""Strategy identification models.

StrategyType enum, ParsedLeg (frozen dataclass), and Strategy (dataclass).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from tastytrade.accounts.models import InstrumentType


class StrategyType(str, Enum):
    """All recognized option strategy types."""

    # Delta-1
    LONG_STOCK = "Long Stock"
    SHORT_STOCK = "Short Stock"
    LONG_CRYPTO = "Long Crypto"
    SHORT_CRYPTO = "Short Crypto"
    LONG_FUTURE = "Long Future"
    SHORT_FUTURE = "Short Future"

    # Single-leg options
    LONG_CALL = "Long Call"
    LONG_PUT = "Long Put"
    NAKED_CALL = "Naked Call"
    NAKED_PUT = "Naked Put"

    # Covered
    COVERED_CALL = "Covered Call"
    PROTECTIVE_PUT = "Protective Put"
    COLLAR = "Collar"

    # Verticals
    BULL_CALL_SPREAD = "Bull Call Spread"
    BEAR_CALL_SPREAD = "Bear Call Spread"
    BULL_PUT_SPREAD = "Bull Put Spread"
    BEAR_PUT_SPREAD = "Bear Put Spread"

    # Straddle/Strangle
    LONG_STRADDLE = "Long Straddle"
    SHORT_STRADDLE = "Short Straddle"
    LONG_STRANGLE = "Long Strangle"
    SHORT_STRANGLE = "Short Strangle"

    # Tastytrade
    JADE_LIZARD = "Jade Lizard"
    COVERED_JADE_LIZARD = "Covered Jade Lizard"
    BIG_LIZARD = "Big Lizard"

    # Iron
    IRON_CONDOR = "Iron Condor"
    IRON_BUTTERFLY = "Iron Butterfly"

    # Butterfly/Condor
    CALL_BUTTERFLY = "Call Butterfly"
    PUT_BUTTERFLY = "Put Butterfly"
    BROKEN_FLY = "Broken Fly"
    IRON_BROKEN_FLY = "Iron Broken Fly"
    CONDOR = "Condor"

    # Calendar/Diagonal
    CALENDAR_SPREAD = "Calendar Spread"
    DIAGONAL_SPREAD = "Diagonal Spread"

    # Other
    RATIO_SPREAD = "Ratio Spread"
    SYNTHETIC_LONG = "Synthetic Long"
    SYNTHETIC_SHORT = "Synthetic Short"
    CUSTOM = "Custom"


@dataclass(frozen=True)
class ParsedLeg:
    """A single position leg enriched with instrument metadata.

    Built by joining SecurityMetrics + instrument data from Redis.
    """

    # Position identity
    streamer_symbol: str
    symbol: str
    underlying: str
    instrument_type: InstrumentType
    signed_quantity: float  # positive=long, negative=short

    # Instrument fields (from broker API) — None for non-options
    option_type: Optional[str] = None  # "C" or "P"
    strike: Optional[Decimal] = None
    expiration: Optional[date] = None
    days_to_expiration: Optional[int] = None

    # Contract multiplier for dollar P&L.
    # Equity options: shares-per-contract (100).
    # Future options: underlying future's notional-multiplier.
    multiplier: Decimal = Decimal("1")

    # Entry value in dollars (from transactions API LIFO replay)
    entry_value: Optional[Decimal] = None

    # Legacy entry price (from position's average-open-price) — kept for
    # backward compatibility but no longer used in P&L calculations.
    average_open_price: Optional[float] = None

    # Market data (from real-time feeds)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    mid_price: Optional[float] = None

    @property
    def is_long(self) -> bool:
        return self.signed_quantity > 0

    @property
    def is_short(self) -> bool:
        return self.signed_quantity < 0

    @property
    def is_call(self) -> bool:
        return self.option_type == "C"

    @property
    def is_put(self) -> bool:
        return self.option_type == "P"

    @property
    def is_option(self) -> bool:
        return self.instrument_type in (
            InstrumentType.EQUITY_OPTION,
            InstrumentType.FUTURE_OPTION,
        )

    @property
    def is_stock(self) -> bool:
        return self.instrument_type in (
            InstrumentType.EQUITY,
            InstrumentType.FUTURE,
            InstrumentType.CRYPTOCURRENCY,
        )

    @property
    def abs_quantity(self) -> float:
        return abs(self.signed_quantity)


@dataclass
class Strategy:
    """A classified option strategy with its component legs."""

    strategy_type: StrategyType
    underlying: str
    legs: tuple[ParsedLeg, ...]

    # Computed properties
    @property
    def net_delta(self) -> Optional[float]:
        deltas = [leg.delta for leg in self.legs if leg.delta is not None]
        if not deltas:
            return None
        return round(
            sum(
                (leg.delta or 0.0) * leg.signed_quantity
                for leg in self.legs
                if leg.delta is not None
            ),
            4,
        )

    @property
    def net_gamma(self) -> Optional[float]:
        vals = [leg.gamma for leg in self.legs if leg.gamma is not None]
        if not vals:
            return None
        return round(
            sum(
                (leg.gamma or 0.0) * leg.signed_quantity
                for leg in self.legs
                if leg.gamma is not None
            ),
            4,
        )

    @property
    def net_theta(self) -> Optional[float]:
        """Dollar-denominated net theta (scaled by contract multiplier)."""
        vals = [leg.theta for leg in self.legs if leg.theta is not None]
        if not vals:
            return None
        return round(
            sum(
                (leg.theta or 0.0) * leg.signed_quantity * float(leg.multiplier)
                for leg in self.legs
                if leg.theta is not None
            ),
            2,
        )

    @property
    def net_vega(self) -> Optional[float]:
        vals = [leg.vega for leg in self.legs if leg.vega is not None]
        if not vals:
            return None
        return round(
            sum(
                (leg.vega or 0.0) * leg.signed_quantity
                for leg in self.legs
                if leg.vega is not None
            ),
            4,
        )

    @property
    def days_to_expiration(self) -> Optional[int]:
        dtes = [
            leg.days_to_expiration
            for leg in self.legs
            if leg.days_to_expiration is not None
        ]
        return min(dtes) if dtes else None

    @property
    def nearest_expiration(self) -> Optional[date]:
        exps = [leg.expiration for leg in self.legs if leg.expiration is not None]
        return min(exps) if exps else None

    @property
    def width(self) -> Optional[Decimal]:
        """Strike width for spreads (difference between strikes)."""
        strikes = sorted({leg.strike for leg in self.legs if leg.strike is not None})
        if len(strikes) >= 2:
            return strikes[-1] - strikes[0]
        return None

    @property
    def max_profit(self) -> Optional[Decimal]:
        """Strategy-type-specific max profit calculation."""
        return compute_max_profit(self)

    @property
    def max_loss(self) -> Optional[Decimal]:
        """Strategy-type-specific max loss calculation."""
        return compute_max_loss(self)


def strategy_multiplier(strategy: Strategy) -> Decimal:
    """Get the contract multiplier for a strategy.

    All legs in a strategy share the same underlying, so the multiplier
    is consistent. Uses the first option leg's multiplier.
    """
    for leg in strategy.legs:
        if leg.is_option:
            return leg.multiplier
    return Decimal("1")


def compute_net_entry_credit_dollars(
    option_legs: list[ParsedLeg],
) -> Optional[Decimal]:
    """Compute the net dollar credit received at entry.

    Uses transaction-derived ``entry_value`` which is already signed by
    the LIFO replay: positive = credit received (Sell to Open), negative =
    debit paid (Buy to Open). Simply sums all leg values.

    Positive result = net credit (sold premium > bought premium).
    Returns None if any leg is missing entry value data.
    """
    if any(leg.entry_value is None for leg in option_legs):
        return None
    total = Decimal("0")
    for leg in option_legs:
        assert leg.entry_value is not None  # guarded above
        total += leg.entry_value
    return total


def compute_max_profit(strategy: Strategy) -> Optional[Decimal]:
    """Compute max profit in dollars based on strategy type and entry prices.

    Uses transaction-derived dollar entry values — not the current mark.
    Max profit is fixed at entry and does not change with market moves.
    Returns None if insufficient data.
    """
    option_legs = [leg for leg in strategy.legs if leg.is_option]
    if not option_legs:
        return None

    st = strategy.strategy_type
    mult = strategy_multiplier(strategy)
    net_credit = compute_net_entry_credit_dollars(option_legs)

    if net_credit is None:
        return None

    if st in (
        StrategyType.BEAR_CALL_SPREAD,
        StrategyType.BULL_PUT_SPREAD,
        StrategyType.IRON_CONDOR,
        StrategyType.SHORT_STRANGLE,
        StrategyType.SHORT_STRADDLE,
        StrategyType.NAKED_CALL,
        StrategyType.NAKED_PUT,
        StrategyType.JADE_LIZARD,
    ):
        # Credit strategies: max profit = net credit received (already in dollars)
        return max(net_credit, Decimal("0")).quantize(Decimal("1"))

    if st in (StrategyType.BULL_CALL_SPREAD, StrategyType.BEAR_PUT_SPREAD):
        # Debit spread: max profit = (width * multiplier) - net debit paid
        w = strategy.width
        if w is None:
            return None
        return max(w * mult + net_credit, Decimal("0")).quantize(Decimal("1"))

    return None


def compute_max_loss(strategy: Strategy) -> Optional[Decimal]:
    """Compute max loss in dollars based on strategy type and entry prices.

    Uses transaction-derived dollar entry values — not the current mark.
    Returns None for unlimited-risk strategies or insufficient data.
    """
    option_legs = [leg for leg in strategy.legs if leg.is_option]
    if not option_legs:
        return None

    st = strategy.strategy_type
    mult = strategy_multiplier(strategy)
    net_credit = compute_net_entry_credit_dollars(option_legs)

    if net_credit is None:
        return None

    # Unlimited risk strategies
    if st in (
        StrategyType.NAKED_CALL,
        StrategyType.SHORT_STRANGLE,
        StrategyType.SHORT_STRADDLE,
    ):
        return None

    if st in (StrategyType.BEAR_CALL_SPREAD, StrategyType.BULL_PUT_SPREAD):
        # Credit spread: max loss = (width * multiplier) - net credit
        w = strategy.width
        if w is None:
            return None
        return max(w * mult - net_credit, Decimal("0")).quantize(Decimal("1"))

    if st in (StrategyType.BULL_CALL_SPREAD, StrategyType.BEAR_PUT_SPREAD):
        # Debit spread: max loss = net debit paid (already in dollars)
        net_debit = -net_credit
        return max(net_debit, Decimal("0")).quantize(Decimal("1"))

    if st == StrategyType.IRON_CONDOR:
        put_strikes = sorted(
            leg.strike for leg in option_legs if leg.is_put and leg.strike
        )
        call_strikes = sorted(
            leg.strike for leg in option_legs if leg.is_call and leg.strike
        )

        put_width = (
            (put_strikes[-1] - put_strikes[0])
            if len(put_strikes) >= 2
            else Decimal("0")
        )
        call_width = (
            (call_strikes[-1] - call_strikes[0])
            if len(call_strikes) >= 2
            else Decimal("0")
        )
        wing_width = max(put_width, call_width)
        return max(wing_width * mult - net_credit, Decimal("0")).quantize(Decimal("1"))

    if st == StrategyType.JADE_LIZARD:
        w = strategy.width
        if w is None:
            return None
        return max(w * mult - net_credit, Decimal("0")).quantize(Decimal("1"))

    return None
