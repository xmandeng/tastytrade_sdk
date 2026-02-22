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

# Mapping from signal interval to default pricing interval.
# "Lower timeframe for accuracy" — use a finer granularity for
# precise entry/exit pricing.
_DEFAULT_PRICING_INTERVALS: dict[str, str] = {
    "1d": "1h",
    "4h": "1h",
    "1h": "15m",
    "30m": "5m",
    "15m": "5m",
    "5m": "1m",
    "1m": "1m",  # 1m is the lowest — no finer resolution
}


def resolve_pricing_interval(
    signal_interval: str, pricing_interval: str | None = None
) -> str:
    """Determine the pricing interval for a given signal interval.

    If pricing_interval is explicitly provided, use it.  Otherwise,
    select the next-lower granularity from the default mapping.

    Args:
        signal_interval: Interval used for signal generation (e.g., "5m").
        pricing_interval: Explicit override.  When None, auto-selected.

    Returns:
        The resolved pricing interval string.
    """
    if pricing_interval is not None:
        return pricing_interval
    return _DEFAULT_PRICING_INTERVALS.get(signal_interval, signal_interval)


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
    engine_type: str = Field(default="hull_macd", description="Signal engine to use")
    source: str = Field(default="backtest", description="Signal source tag")

    @property
    def resolved_pricing_interval(self) -> str:
        """Pricing interval, auto-selecting from signal interval if not set."""
        return resolve_pricing_interval(self.signal_interval, self.pricing_interval)

    @property
    def signal_symbol(self) -> str:
        """Symbol with signal interval suffix for Redis channels."""
        return f"{self.symbol}{{={self.signal_interval}}}"

    @property
    def pricing_symbol(self) -> str:
        """Symbol with pricing interval suffix for Redis channels."""
        interval = self.resolved_pricing_interval
        return f"{self.symbol}{{={interval}}}"
