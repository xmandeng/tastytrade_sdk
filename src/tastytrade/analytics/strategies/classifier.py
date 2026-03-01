"""Greedy strategy classification engine.

Groups positions by underlying, then applies pattern matchers
from most-complex to simplest. Matched legs are consumed; remaining
legs become single-leg strategies.
"""

import json
import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from tastytrade.accounts.models import InstrumentType
from tastytrade.analytics.metrics import SecurityMetrics
from tastytrade.analytics.strategies.models import ParsedLeg, Strategy
from tastytrade.analytics.strategies.patterns import (
    MULTI_LEG_MATCHERS,
    match_single_leg,
)

logger = logging.getLogger(__name__)


def snap_to_option_tick(
    price: float,
    tick_sizes: list[dict[str, str]],
) -> float:
    """Snap a truncated future-option price to the nearest valid tick.

    The TastyTrade Position API truncates average-open-price to ~2 decimal
    places for future options. The underlying future's ``option-tick-sizes``
    tells us the minimum price increment, so we can recover the true fill.

    Args:
        price: The truncated average-open-price from the Position API.
        tick_sizes: The ``option-tick-sizes`` list from the underlying future
            instrument (e.g. ``[{"threshold": "5.0", "value": "0.05"}, {"value": "0.5"}]``).

    Returns:
        The price snapped to the nearest valid tick.
    """
    if not tick_sizes or price <= 0:
        return price

    price_dec = Decimal(str(price))

    # Find the correct tick size for this price level.
    # Entries with a threshold apply when price < threshold (ascending order).
    # The entry without a threshold is the catch-all for the highest tier.
    tick = None
    for entry in tick_sizes:
        threshold = entry.get("threshold")
        if threshold is not None and price_dec < Decimal(str(threshold)):
            tick = Decimal(str(entry["value"]))
            break
    if tick is None:
        # Use the catch-all (entry without threshold)
        for entry in tick_sizes:
            if "threshold" not in entry:
                tick = Decimal(str(entry["value"]))
                break
    if tick is None or tick == 0:
        return price

    snapped = (price_dec / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
    return float(snapped)


class StrategyClassifier:
    """Classifies positions into named option strategies via greedy pattern matching."""

    @staticmethod
    def build_parsed_leg(
        security: SecurityMetrics,
        instruments: dict[str, Any],
    ) -> ParsedLeg:
        """Build a ParsedLeg by joining SecurityMetrics + instrument data."""
        signed_qty = security.quantity
        if security.quantity_direction.value == "Short":
            signed_qty = -abs(signed_qty)
        elif security.quantity_direction.value == "Long":
            signed_qty = abs(signed_qty)

        # Look up instrument metadata
        instrument_data = instruments.get(security.symbol)
        option_type: Optional[str] = None
        strike: Optional[Decimal] = None
        expiration = None
        dte: Optional[int] = None

        if instrument_data is not None:
            if isinstance(instrument_data, str):
                instrument_data = json.loads(instrument_data)
            option_type = instrument_data.get("option-type")
            strike_raw = instrument_data.get("strike-price")
            if strike_raw is not None:
                strike = Decimal(str(strike_raw))
            exp_raw = instrument_data.get("expiration-date")
            if exp_raw is not None:
                from datetime import date

                expiration = (
                    date.fromisoformat(exp_raw) if isinstance(exp_raw, str) else exp_raw
                )
            dte_raw = instrument_data.get("days-to-expiration")
            dte = int(dte_raw) if dte_raw is not None else None

        # Determine contract multiplier for dollar P&L
        multiplier = Decimal("1")
        underlying_data: Any = None
        if security.instrument_type == InstrumentType.EQUITY_OPTION:
            if instrument_data and instrument_data.get("shares-per-contract"):
                multiplier = Decimal(str(instrument_data["shares-per-contract"]))
        elif security.instrument_type == InstrumentType.FUTURE_OPTION:
            # Look up the underlying future's notional-multiplier
            underlying_sym = security.underlying_symbol
            if underlying_sym:
                underlying_data = instruments.get(underlying_sym)
                if underlying_data is not None:
                    if isinstance(underlying_data, str):
                        underlying_data = json.loads(underlying_data)
                    nm = underlying_data.get("notional-multiplier")
                    if nm is not None:
                        multiplier = Decimal(str(nm))

        # Recover average_open_price precision for future options.
        # The Position API truncates prices to ~2 decimals; the underlying
        # future's option-tick-sizes lets us snap back to the true fill.
        avg_open = security.average_open_price
        if avg_open is not None and avg_open == 0.0:
            avg_open = None  # API returns 0.0 for some futures (e.g. /6E)
        if (
            avg_open is not None
            and security.instrument_type == InstrumentType.FUTURE_OPTION
            and underlying_data is not None
        ):
            tick_sizes = underlying_data.get("option-tick-sizes", [])
            if tick_sizes:
                avg_open = snap_to_option_tick(avg_open, tick_sizes)

        return ParsedLeg(
            streamer_symbol=security.streamer_symbol,
            symbol=security.symbol,
            underlying=security.underlying_symbol or security.symbol,
            instrument_type=security.instrument_type,
            signed_quantity=signed_qty,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            days_to_expiration=dte,
            multiplier=multiplier,
            average_open_price=avg_open,
            delta=security.delta,
            gamma=security.gamma,
            theta=security.theta,
            vega=security.vega,
            mid_price=security.mid_price,
        )

    def classify(
        self,
        securities: dict[str, SecurityMetrics],
        instruments: dict[str, Any],
    ) -> list[Strategy]:
        """Classify all positions into strategies.

        1. Build ParsedLeg for each security
        2. Group by underlying
        3. For each group: greedy match from most-complex to simplest
        4. Remaining unmatched legs -> single-leg strategies
        """
        # Build parsed legs
        all_legs: list[ParsedLeg] = []
        for security in securities.values():
            leg = self.build_parsed_leg(security, instruments)
            all_legs.append(leg)

        # Group by underlying
        by_underlying: dict[str, list[ParsedLeg]] = defaultdict(list)
        for leg in all_legs:
            by_underlying[leg.underlying].append(leg)

        strategies: list[Strategy] = []

        for underlying, underlying_legs in by_underlying.items():
            remaining = list(underlying_legs)

            # Greedy matching: most complex patterns first
            for matcher in MULTI_LEG_MATCHERS:
                while remaining:
                    result = matcher(remaining)
                    if result is None:
                        break
                    strategies.append(
                        Strategy(
                            strategy_type=result.strategy_type,
                            underlying=underlying,
                            legs=result.matched_legs,
                        )
                    )
                    # Remove matched legs from remaining
                    matched_ids = {
                        id(matched_leg) for matched_leg in result.matched_legs
                    }
                    remaining = [leg for leg in remaining if id(leg) not in matched_ids]

            # Remaining legs -> single-leg strategies
            for leg in remaining:
                strategy_type = match_single_leg(leg)
                strategies.append(
                    Strategy(
                        strategy_type=strategy_type,
                        underlying=underlying,
                        legs=(leg,),
                    )
                )

        return strategies
