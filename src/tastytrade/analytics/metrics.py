"""Security-level position metrics engine.

Joins static position data with real-time DXLink Quote events into a flat,
per-position DataFrame keyed by streamer_symbol. Greeks fields carry
theoretically correct defaults for delta-1 instruments and None for options.
"""

import logging
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Optional

import pandas as pd

from tastytrade.accounts.models import InstrumentType, Position, QuantityDirection
from tastytrade.messaging.models.events import QuoteEvent

logger = logging.getLogger(__name__)

# Instrument types that are delta-1 (not options)
DELTA_1_TYPES: frozenset[InstrumentType] = frozenset(
    {
        InstrumentType.EQUITY,
        InstrumentType.FUTURE,
        InstrumentType.CRYPTOCURRENCY,
        InstrumentType.BOND,
        InstrumentType.CURRENCY_PAIR,
        InstrumentType.EQUITY_OFFERING,
        InstrumentType.FIXED_INCOME_SECURITY,
        InstrumentType.INDEX,
        InstrumentType.LIQUIDITY_POOL,
        InstrumentType.UNKNOWN,
        InstrumentType.WARRANT,
    }
)

OPTION_TYPES: frozenset[InstrumentType] = frozenset(
    {
        InstrumentType.EQUITY_OPTION,
        InstrumentType.FUTURE_OPTION,
    }
)


@dataclass
class SecurityMetrics:
    """Mutable per-position metrics row, keyed by streamer_symbol.

    Position fields are set from load_positions() and updated via
    on_position_update(). Market data fields are updated from real-time
    QuoteEvent. Greeks carry theoretical defaults for delta-1 instruments
    and None for options.
    """

    # Position identity
    symbol: str
    streamer_symbol: str
    instrument_type: InstrumentType
    quantity: float
    quantity_direction: QuantityDirection
    average_open_price: Optional[float] = None
    multiplier: Optional[float] = None
    underlying_symbol: Optional[str] = None

    # Market data (from QuoteEvent)
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    mid_price: Optional[float] = None

    # Greeks (theoretical defaults for delta-1, None for options)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    implied_volatility: Optional[float] = None

    # Staleness timestamps
    price_updated_at: Optional[datetime] = None
    greeks_updated_at: Optional[datetime] = None
    position_updated_at: Optional[datetime] = None


class MetricsTracker:
    """Tracks per-position metrics, joining positions with live market data.

    Securities dict is keyed by streamer_symbol (the DXLink eventSymbol).
    Positions without a streamer_symbol are silently skipped.
    """

    def __init__(self) -> None:
        self.securities: dict[str, SecurityMetrics] = {}

    def load_positions(self, positions: list[Position]) -> None:
        """Create SecurityMetrics for each position with a streamer_symbol.

        Greeks defaults are set based on instrument type:
          - Delta-1: delta=+1.0 (Long) or -1.0 (Short), gamma/theta/vega/rho=0.0
          - Options: all Greeks=None (awaiting GreeksEvent from TT-37)
        """
        now = datetime.now()
        for position in positions:
            if position.streamer_symbol is None:
                logger.debug(
                    "Skipping position %s: no streamer_symbol", position.symbol
                )
                continue

            if position.instrument_type in DELTA_1_TYPES:
                if position.quantity_direction == QuantityDirection.LONG:
                    delta: Optional[float] = 1.0
                elif position.quantity_direction == QuantityDirection.SHORT:
                    delta = -1.0
                else:
                    delta = 0.0
                gamma: Optional[float] = 0.0
                theta: Optional[float] = 0.0
                vega: Optional[float] = 0.0
                rho: Optional[float] = 0.0
                greeks_updated_at: Optional[datetime] = now
            else:
                delta = None
                gamma = None
                theta = None
                vega = None
                rho = None
                greeks_updated_at = None

            self.securities[position.streamer_symbol] = SecurityMetrics(
                symbol=position.symbol,
                streamer_symbol=position.streamer_symbol,
                instrument_type=position.instrument_type,
                quantity=position.quantity,
                quantity_direction=position.quantity_direction,
                average_open_price=position.average_open_price,
                multiplier=position.multiplier,
                underlying_symbol=position.underlying_symbol,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
                rho=rho,
                implied_volatility=None,
                greeks_updated_at=greeks_updated_at,
                position_updated_at=now,
            )

        logger.info(
            "Loaded %d positions (%d with streamer symbols)",
            len(positions),
            len(self.securities),
        )

    def on_quote_event(self, event: QuoteEvent) -> None:
        """Update bid/ask/mid prices from a QuoteEvent.

        Unknown eventSymbols are silently ignored.
        """
        metrics = self.securities.get(event.eventSymbol)
        if metrics is None:
            return

        metrics.bid_price = event.bidPrice
        metrics.ask_price = event.askPrice
        if event.bidPrice is not None and event.askPrice is not None:
            metrics.mid_price = round((event.bidPrice + event.askPrice) / 2, 2)
        metrics.price_updated_at = datetime.now()

    def on_position_update(self, position: Position) -> None:
        """Merge position field changes while preserving market data and Greeks.

        If the position is new (not previously tracked), it is added via
        load_positions. Positions without streamer_symbol are skipped.
        """
        if position.streamer_symbol is None:
            logger.debug(
                "Skipping position update %s: no streamer_symbol", position.symbol
            )
            return

        metrics = self.securities.get(position.streamer_symbol)
        if metrics is None:
            self.load_positions([position])
            return

        metrics.symbol = position.symbol
        metrics.instrument_type = position.instrument_type
        metrics.quantity = position.quantity
        metrics.quantity_direction = position.quantity_direction
        metrics.average_open_price = position.average_open_price
        metrics.multiplier = position.multiplier
        metrics.underlying_symbol = position.underlying_symbol
        metrics.position_updated_at = datetime.now()

    def get_streamer_symbols(self) -> set[str]:
        """Return the set of streamer symbols being tracked."""
        return set(self.securities.keys())

    @property
    def df(self) -> pd.DataFrame:
        """Return a Pandas DataFrame with one row per tracked security."""
        if not self.securities:
            return pd.DataFrame(columns=[f.name for f in fields(SecurityMetrics)])
        return pd.DataFrame([vars(m) for m in self.securities.values()])
