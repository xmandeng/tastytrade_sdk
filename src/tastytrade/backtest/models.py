"""Backtest models — BacktestSignal, BacktestConfig.

BacktestSignal extends TradeSignal with backtest-specific metadata so
that backtest signals are automatically distinguishable from live signals
in both Redis channels and InfluxDB measurements.

BacktestConfig is a frozen configuration for a single backtest run.
"""

from datetime import date
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from tastytrade.analytics.engines.models import TradeSignal

# DXLink uses compact interval format: "m" for 1-minute, "h" for 1-hour,
# "d" for daily.  Multi-unit intervals like "5m", "15m" stay as-is.
DXLINK_NORMALIZATION: dict[str, str] = {
    "1m": "m",
    "1h": "h",
    "1d": "d",
}

# Mapping from signal interval (DXLink format) to default pricing interval.
# "Lower timeframe for accuracy" — use a finer granularity for
# precise entry/exit pricing.
DEFAULT_PRICING_INTERVALS: dict[str, str] = {
    "d": "h",
    "h": "15m",
    "30m": "5m",
    "15m": "5m",
    "5m": "m",
    "m": "m",  # 1m is the lowest — no finer resolution
}


def to_dxlink_interval(interval: str) -> str:
    """Convert a user-friendly interval to DXLink eventSymbol format.

    DXLink uses compact notation: ``m`` for 1-minute, ``h`` for 1-hour,
    ``d`` for daily.  Multi-unit intervals (``5m``, ``15m``, ``30m``)
    are already in DXLink format and pass through unchanged.

    Examples::

        to_dxlink_interval("1m") → "m"
        to_dxlink_interval("5m") → "5m"
        to_dxlink_interval("1h") → "h"
        to_dxlink_interval("1d") → "d"
    """
    return DXLINK_NORMALIZATION.get(interval, interval)


def resolve_pricing_interval(
    signal_interval: str, pricing_interval: str | None = None
) -> str:
    """Determine the pricing interval for a given signal interval.

    If pricing_interval is explicitly provided, normalize and return it.
    Otherwise, select the next-lower granularity from the default mapping.

    Both input and output use DXLink format (``m``, ``h``, ``d``).

    Args:
        signal_interval: Interval used for signal generation (e.g., "5m").
        pricing_interval: Explicit override.  When None, auto-selected.

    Returns:
        The resolved pricing interval string in DXLink format.
    """
    if pricing_interval is not None:
        return to_dxlink_interval(pricing_interval)
    normalized = to_dxlink_interval(signal_interval)
    return DEFAULT_PRICING_INTERVALS.get(normalized, normalized)


class BacktestSignal(TradeSignal):
    """A trade signal produced during backtest replay.

    Extends TradeSignal with backtest metadata so it is automatically
    distinguishable in Redis channels (market:BacktestSignal:*) and
    InfluxDB measurements (BacktestSignal vs TradeSignal).
    """

    event_type: str = "backtest_signal"
    backtest_id: str = Field(description="Unique backtest run identifier")
    source: str = Field(
        default="backtest", description="Signal source: backtest or live"
    )
    entry_price: float | None = Field(
        default=None,
        description="Entry price from pricing-interval candle at signal time",
    )
    signal_interval: str = Field(
        description="Interval used for signal generation (e.g., 5m)"
    )
    pricing_interval: str = Field(
        description="Interval used for entry/exit pricing (e.g., 1m)"
    )


class BacktestConfig(BaseModel):
    """Frozen configuration for a single backtest run.

    All parameters needed to fully specify and reproduce a backtest.
    """

    model_config = ConfigDict(frozen=True)

    backtest_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique run identifier (auto-generated UUID)",
    )
    symbol: str = Field(description="Market symbol (e.g., SPX, NVDA)")
    signal_interval: str = Field(
        default="5m", description="Candle interval for signal generation"
    )
    pricing_interval: Optional[str] = Field(
        default=None,
        description="Candle interval for entry/exit pricing (auto-selected if None)",
    )
    start_date: date = Field(description="Backtest start date")
    end_date: date = Field(description="Backtest end date")
    source: str = Field(default="backtest", description="Signal source tag")

    @property
    def resolved_pricing_interval(self) -> str:
        """Pricing interval, auto-selecting from signal interval if not set."""
        return resolve_pricing_interval(self.signal_interval, self.pricing_interval)

    @property
    def signal_symbol(self) -> str:
        """Symbol with signal interval suffix for Redis channels (DXLink format)."""
        return f"{self.symbol}{{={to_dxlink_interval(self.signal_interval)}}}"

    @property
    def pricing_symbol(self) -> str:
        """Symbol with pricing interval suffix for Redis channels (DXLink format)."""
        interval = self.resolved_pricing_interval  # already DXLink-normalized
        return f"{self.symbol}{{={interval}}}"
