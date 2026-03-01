"""Pattern matchers for option strategy identification.

Each matcher: match_X(legs: list[ParsedLeg]) -> MatchResult | None

Priority order (greedy -- most legs first):
1. 4+ legs: Iron Condor, Iron Butterfly, Covered Jade Lizard, Big Lizard, Butterfly
2. 3 legs: Jade Lizard, Collar
3. 2 legs (with stock): Covered Call, Protective Put
4. 2 legs (same exp, same type): Vertical spreads, Ratio Spread
5. 2 legs (same exp, diff type): Straddle, Strangle, Synthetic
6. 2 legs (diff exp): Calendar, Diagonal
7. 1 leg: single positions
"""

import logging
from dataclasses import dataclass
from itertools import combinations
from typing import Callable

from tastytrade.analytics.strategies.models import ParsedLeg, StrategyType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchResult:
    """Result of a successful pattern match."""

    strategy_type: StrategyType
    matched_legs: tuple[ParsedLeg, ...]


def same_expiration(legs: list[ParsedLeg]) -> bool:
    """Check if all option legs share the same expiration."""
    exps = {leg.expiration for leg in legs if leg.expiration is not None}
    return len(exps) == 1


def same_abs_quantity(legs: list[ParsedLeg]) -> bool:
    """Check if all legs have the same absolute quantity."""
    qtys = {leg.abs_quantity for leg in legs}
    return len(qtys) == 1


# ===== 4-leg patterns =====


def match_iron_condor(legs: list[ParsedLeg]) -> MatchResult | None:
    """Iron Condor: 4 options, same exp, same qty.
    Short put + long put (lower) + short call + long call (higher).
    Put strikes < Call strikes.
    """
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 4:
        return None

    for combo in combinations(options, 4):
        combo_list = list(combo)
        if not same_expiration(combo_list) or not same_abs_quantity(combo_list):
            continue

        puts = sorted(
            [leg for leg in combo_list if leg.is_put],
            key=lambda x: x.strike or 0,
        )
        calls = sorted(
            [leg for leg in combo_list if leg.is_call],
            key=lambda x: x.strike or 0,
        )

        if len(puts) != 2 or len(calls) != 2:
            continue

        # Long lower put, short higher put, short lower call, long higher call
        if (
            puts[0].is_long
            and puts[1].is_short
            and calls[0].is_short
            and calls[1].is_long
        ):
            # Put strikes must be below call strikes
            if puts[1].strike is not None and calls[0].strike is not None:
                if puts[1].strike < calls[0].strike:
                    return MatchResult(StrategyType.IRON_CONDOR, tuple(combo_list))

    return None


def match_iron_butterfly(legs: list[ParsedLeg]) -> MatchResult | None:
    """Iron Butterfly: 4 options, same exp, same qty.
    Like iron condor but short put strike == short call strike.
    """
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 4:
        return None

    for combo in combinations(options, 4):
        combo_list = list(combo)
        if not same_expiration(combo_list) or not same_abs_quantity(combo_list):
            continue

        puts = sorted(
            [leg for leg in combo_list if leg.is_put],
            key=lambda x: x.strike or 0,
        )
        calls = sorted(
            [leg for leg in combo_list if leg.is_call],
            key=lambda x: x.strike or 0,
        )

        if len(puts) != 2 or len(calls) != 2:
            continue

        if (
            puts[0].is_long
            and puts[1].is_short
            and calls[0].is_short
            and calls[1].is_long
        ):
            if puts[1].strike is not None and calls[0].strike is not None:
                if puts[1].strike == calls[0].strike:
                    return MatchResult(StrategyType.IRON_BUTTERFLY, tuple(combo_list))

    return None


def match_call_butterfly(legs: list[ParsedLeg]) -> MatchResult | None:
    """Call Butterfly: 3 calls, same exp. Buy 1 low, sell 2 middle, buy 1 high.
    Middle strike = (low + high) / 2. Qty ratio 1:2:1.
    """
    options = [leg for leg in legs if leg.is_option and leg.is_call]
    if len(options) < 3:
        return None

    for combo in combinations(options, 3):
        combo_list = sorted(combo, key=lambda x: x.strike or 0)
        if not same_expiration(list(combo_list)):
            continue

        low, mid, high = combo_list
        if low.strike is None or mid.strike is None or high.strike is None:
            continue

        # Check equal spacing
        if mid.strike - low.strike != high.strike - mid.strike:
            continue

        # Buy 1 low, sell 2 middle, buy 1 high
        if (
            low.is_long
            and mid.is_short
            and high.is_long
            and low.abs_quantity == high.abs_quantity
            and mid.abs_quantity == 2 * low.abs_quantity
        ):
            return MatchResult(StrategyType.CALL_BUTTERFLY, tuple(combo_list))

    return None


def match_put_butterfly(legs: list[ParsedLeg]) -> MatchResult | None:
    """Put Butterfly: 3 puts, same exp. Buy 1 low, sell 2 middle, buy 1 high."""
    options = [leg for leg in legs if leg.is_option and leg.is_put]
    if len(options) < 3:
        return None

    for combo in combinations(options, 3):
        combo_list = sorted(combo, key=lambda x: x.strike or 0)
        if not same_expiration(list(combo_list)):
            continue

        low, mid, high = combo_list
        if low.strike is None or mid.strike is None or high.strike is None:
            continue

        if mid.strike - low.strike != high.strike - mid.strike:
            continue

        if (
            low.is_long
            and mid.is_short
            and high.is_long
            and low.abs_quantity == high.abs_quantity
            and mid.abs_quantity == 2 * low.abs_quantity
        ):
            return MatchResult(StrategyType.PUT_BUTTERFLY, tuple(combo_list))

    return None


def match_covered_jade_lizard(legs: list[ParsedLeg]) -> MatchResult | None:
    """Covered Jade Lizard: long stock + short put + bear call spread.
    4 legs total: 1 stock + 3 options.
    """
    stocks = [leg for leg in legs if leg.is_stock and leg.is_long]
    options = [leg for leg in legs if leg.is_option]

    if not stocks or len(options) < 3:
        return None

    stock = stocks[0]

    for combo in combinations(options, 3):
        combo_list = list(combo)
        if not same_expiration(combo_list):
            continue

        short_puts = [leg for leg in combo_list if leg.is_put and leg.is_short]
        short_calls = [leg for leg in combo_list if leg.is_call and leg.is_short]
        long_calls = [leg for leg in combo_list if leg.is_call and leg.is_long]

        if len(short_puts) != 1 or len(short_calls) != 1 or len(long_calls) != 1:
            continue

        # Bear call spread: short call at lower strike, long call at higher
        if (
            short_calls[0].strike is not None
            and long_calls[0].strike is not None
            and short_calls[0].strike < long_calls[0].strike
        ):
            matched = (stock,) + tuple(combo_list)
            return MatchResult(StrategyType.COVERED_JADE_LIZARD, matched)

    return None


def match_big_lizard(legs: list[ParsedLeg]) -> MatchResult | None:
    """Big Lizard: short straddle + long OTM call.
    3 options: short call + short put at same strike + long call at higher strike.
    """
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 3:
        return None

    for combo in combinations(options, 3):
        combo_list = list(combo)
        if not same_expiration(combo_list):
            continue

        short_calls = [leg for leg in combo_list if leg.is_call and leg.is_short]
        short_puts = [leg for leg in combo_list if leg.is_put and leg.is_short]
        long_calls = [leg for leg in combo_list if leg.is_call and leg.is_long]

        if len(short_calls) != 1 or len(short_puts) != 1 or len(long_calls) != 1:
            continue

        # Short straddle: same strike
        if short_calls[0].strike != short_puts[0].strike:
            continue

        # Long call at higher strike
        if (
            long_calls[0].strike is not None
            and short_calls[0].strike is not None
            and long_calls[0].strike > short_calls[0].strike
        ):
            return MatchResult(StrategyType.BIG_LIZARD, tuple(combo_list))

    return None


# ===== 3-leg patterns =====


def match_jade_lizard(legs: list[ParsedLeg]) -> MatchResult | None:
    """Jade Lizard: short put + short call vertical OR short call + short put vertical.

    Variant A: short put + bear call spread (short call + long higher call).
    Variant B: short call + bull put spread (short put + long lower put).
    3 options, same exp, same abs quantity.
    """
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 3:
        return None

    for combo in combinations(options, 3):
        combo_list = list(combo)
        if not same_expiration(combo_list):
            continue

        if not same_abs_quantity(combo_list):
            continue

        short_puts = [leg for leg in combo_list if leg.is_put and leg.is_short]
        short_calls = [leg for leg in combo_list if leg.is_call and leg.is_short]
        long_calls = [leg for leg in combo_list if leg.is_call and leg.is_long]
        long_puts = [leg for leg in combo_list if leg.is_put and leg.is_long]

        # Variant A: short put + bear call spread (1 short put, 1 short call, 1 long call)
        if len(short_puts) == 1 and len(short_calls) == 1 and len(long_calls) == 1:
            if (
                short_calls[0].strike is not None
                and long_calls[0].strike is not None
                and short_calls[0].strike < long_calls[0].strike
            ):
                return MatchResult(StrategyType.JADE_LIZARD, tuple(combo_list))

        # Variant B: short call + bull put spread (1 short call, 1 short put, 1 long put)
        if len(short_calls) == 1 and len(short_puts) == 1 and len(long_puts) == 1:
            if (
                long_puts[0].strike is not None
                and short_puts[0].strike is not None
                and long_puts[0].strike < short_puts[0].strike
            ):
                return MatchResult(StrategyType.JADE_LIZARD, tuple(combo_list))

    return None


def match_collar(legs: list[ParsedLeg]) -> MatchResult | None:
    """Collar: long stock + long put + short call, same exp."""
    stocks = [leg for leg in legs if leg.is_stock and leg.is_long]
    options = [leg for leg in legs if leg.is_option]

    if not stocks or len(options) < 2:
        return None

    stock = stocks[0]

    for combo in combinations(options, 2):
        combo_list = list(combo)
        if not same_expiration(combo_list):
            continue

        long_puts = [leg for leg in combo_list if leg.is_put and leg.is_long]
        short_calls = [leg for leg in combo_list if leg.is_call and leg.is_short]

        if len(long_puts) != 1 or len(short_calls) != 1:
            continue

        matched = (stock,) + tuple(combo_list)
        return MatchResult(StrategyType.COLLAR, matched)

    return None


# ===== 2-leg patterns (with stock) =====


def match_covered_call(legs: list[ParsedLeg]) -> MatchResult | None:
    """Covered Call: long stock + short call."""
    stocks = [leg for leg in legs if leg.is_stock and leg.is_long]
    short_calls = [
        leg for leg in legs if leg.is_option and leg.is_call and leg.is_short
    ]

    if not stocks or not short_calls:
        return None

    return MatchResult(StrategyType.COVERED_CALL, (stocks[0], short_calls[0]))


def match_protective_put(legs: list[ParsedLeg]) -> MatchResult | None:
    """Protective Put: long stock + long put."""
    stocks = [leg for leg in legs if leg.is_stock and leg.is_long]
    long_puts = [leg for leg in legs if leg.is_option and leg.is_put and leg.is_long]

    if not stocks or not long_puts:
        return None

    return MatchResult(StrategyType.PROTECTIVE_PUT, (stocks[0], long_puts[0]))


# ===== 2-leg patterns (same exp, same type) =====


def match_vertical_spread(legs: list[ParsedLeg]) -> MatchResult | None:
    """Match vertical spreads: 2 options, same type, same exp, diff strikes, same qty."""
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 2:
        return None

    for combo in combinations(options, 2):
        a, b = combo
        if a.option_type != b.option_type:
            continue
        if a.expiration != b.expiration or a.expiration is None:
            continue
        if a.strike == b.strike or a.strike is None or b.strike is None:
            continue
        if a.abs_quantity != b.abs_quantity:
            continue

        low, high = (a, b) if a.strike < b.strike else (b, a)

        if a.is_call:
            if low.is_long and high.is_short:
                return MatchResult(StrategyType.BULL_CALL_SPREAD, (low, high))
            if low.is_short and high.is_long:
                return MatchResult(StrategyType.BEAR_CALL_SPREAD, (low, high))
        else:  # puts
            if low.is_long and high.is_short:
                return MatchResult(StrategyType.BEAR_PUT_SPREAD, (low, high))
            if low.is_short and high.is_long:
                return MatchResult(StrategyType.BULL_PUT_SPREAD, (low, high))

    return None


def match_ratio_spread(legs: list[ParsedLeg]) -> MatchResult | None:
    """Ratio Spread: 2 options, same type, same exp, different quantities."""
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 2:
        return None

    for combo in combinations(options, 2):
        a, b = combo
        if a.option_type != b.option_type:
            continue
        if a.expiration != b.expiration or a.expiration is None:
            continue
        if a.strike == b.strike or a.strike is None or b.strike is None:
            continue
        # Must have different quantities (distinguishes from vertical)
        if a.abs_quantity == b.abs_quantity:
            continue
        # One long, one short
        if (a.is_long and b.is_short) or (a.is_short and b.is_long):
            return MatchResult(StrategyType.RATIO_SPREAD, tuple(combo))

    return None


# ===== 2-leg patterns (same exp, different type) =====


def match_straddle(legs: list[ParsedLeg]) -> MatchResult | None:
    """Straddle: call + put, same exp, same strike, same qty, same direction."""
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 2:
        return None

    for combo in combinations(options, 2):
        a, b = combo
        if a.option_type == b.option_type:
            continue
        if a.expiration != b.expiration or a.expiration is None:
            continue
        if a.strike != b.strike or a.strike is None:
            continue
        if a.abs_quantity != b.abs_quantity:
            continue
        if a.is_long != b.is_long:
            continue

        if a.is_long:
            return MatchResult(StrategyType.LONG_STRADDLE, tuple(combo))
        else:
            return MatchResult(StrategyType.SHORT_STRADDLE, tuple(combo))

    return None


def match_strangle(legs: list[ParsedLeg]) -> MatchResult | None:
    """Strangle: call + put, same exp, different strikes, same qty, same direction."""
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 2:
        return None

    for combo in combinations(options, 2):
        a, b = combo
        if a.option_type == b.option_type:
            continue
        if a.expiration != b.expiration or a.expiration is None:
            continue
        if a.strike == b.strike:
            continue
        if a.strike is None or b.strike is None:
            continue
        if a.abs_quantity != b.abs_quantity:
            continue
        if a.is_long != b.is_long:
            continue

        if a.is_long:
            return MatchResult(StrategyType.LONG_STRANGLE, tuple(combo))
        else:
            return MatchResult(StrategyType.SHORT_STRANGLE, tuple(combo))

    return None


def match_synthetic(legs: list[ParsedLeg]) -> MatchResult | None:
    """Synthetic Long/Short: call + put, same exp, same strike, opposite directions."""
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 2:
        return None

    for combo in combinations(options, 2):
        a, b = combo
        if a.option_type == b.option_type:
            continue
        if a.expiration != b.expiration or a.expiration is None:
            continue
        if a.strike != b.strike or a.strike is None:
            continue
        if a.abs_quantity != b.abs_quantity:
            continue
        if a.is_long == b.is_long:
            continue

        call = a if a.is_call else b
        put = b if a.is_call else a

        if call.is_long and put.is_short:
            return MatchResult(StrategyType.SYNTHETIC_LONG, tuple(combo))
        else:
            return MatchResult(StrategyType.SYNTHETIC_SHORT, tuple(combo))

    return None


# ===== 2-leg patterns (different exp) =====


def match_calendar_spread(legs: list[ParsedLeg]) -> MatchResult | None:
    """Calendar Spread: 2 options, same type, same strike, different exp."""
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 2:
        return None

    for combo in combinations(options, 2):
        a, b = combo
        if a.option_type != b.option_type:
            continue
        if a.strike != b.strike or a.strike is None:
            continue
        if a.expiration == b.expiration:
            continue
        if a.expiration is None or b.expiration is None:
            continue
        if a.abs_quantity != b.abs_quantity:
            continue

        return MatchResult(StrategyType.CALENDAR_SPREAD, tuple(combo))

    return None


def match_diagonal_spread(legs: list[ParsedLeg]) -> MatchResult | None:
    """Diagonal Spread: 2 options, same type, different strike, different exp."""
    options = [leg for leg in legs if leg.is_option]
    if len(options) < 2:
        return None

    for combo in combinations(options, 2):
        a, b = combo
        if a.option_type != b.option_type:
            continue
        if a.strike == b.strike:
            continue
        if a.strike is None or b.strike is None:
            continue
        if a.expiration == b.expiration:
            continue
        if a.expiration is None or b.expiration is None:
            continue
        if a.abs_quantity != b.abs_quantity:
            continue

        return MatchResult(StrategyType.DIAGONAL_SPREAD, tuple(combo))

    return None


# ===== 1-leg patterns =====


def match_single_leg(leg: ParsedLeg) -> StrategyType:
    """Classify a single unmatched leg."""
    from tastytrade.accounts.models import InstrumentType

    if leg.instrument_type == InstrumentType.EQUITY:
        return StrategyType.LONG_STOCK if leg.is_long else StrategyType.SHORT_STOCK
    if leg.instrument_type == InstrumentType.FUTURE:
        return StrategyType.LONG_FUTURE if leg.is_long else StrategyType.SHORT_FUTURE
    if leg.instrument_type == InstrumentType.CRYPTOCURRENCY:
        return StrategyType.LONG_CRYPTO if leg.is_long else StrategyType.SHORT_CRYPTO
    if leg.is_call:
        return StrategyType.LONG_CALL if leg.is_long else StrategyType.NAKED_CALL
    if leg.is_put:
        return StrategyType.LONG_PUT if leg.is_long else StrategyType.NAKED_PUT
    return StrategyType.CUSTOM


# ===== Ordered matcher list =====

MULTI_LEG_MATCHERS: list[Callable[[list[ParsedLeg]], MatchResult | None]] = [
    # 4+ legs first
    match_iron_condor,
    match_iron_butterfly,
    match_covered_jade_lizard,
    match_big_lizard,
    match_call_butterfly,
    match_put_butterfly,
    # 3 legs
    match_jade_lizard,
    match_collar,
    # 2 legs with stock
    match_covered_call,
    match_protective_put,
    # 2 legs same exp same type
    match_vertical_spread,
    match_ratio_spread,
    # 2 legs same exp diff type
    match_straddle,
    match_strangle,
    match_synthetic,
    # 2 legs diff exp
    match_calendar_spread,
    match_diagonal_spread,
]
