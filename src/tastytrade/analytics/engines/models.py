"""Trade signal models for the signal detection engine.

Defines SignalDirection, SignalType enums and the TradeSignal model that
extends BaseAnnotation for native InfluxDB persistence and chart rendering.
"""

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import Field

from tastytrade.analytics.visualizations.models import BaseAnnotation

if TYPE_CHECKING:
    from tastytrade.analytics.visualizations.models import VerticalLine


class SignalDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class SignalType(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class TradeSignal(BaseAnnotation):
    """A trade signal event emitted when indicator confluence is detected.

    Extends BaseAnnotation so it flows through the EventHandler processor
    chain — the TelegrafHTTPEventProcessor writes it to InfluxDB as a
    ``trade_signal`` measurement, and chart code can render it as an
    annotation overlay.
    """

    event_type: str = "trade_signal"
    signal_type: str = Field(description="OPEN or CLOSE")
    direction: str = Field(description="BULLISH or BEARISH")
    engine: str = Field(description="Engine name that produced this signal")
    hull_direction: str = Field(
        description="Hull MA direction at signal time (Up/Down)"
    )
    hull_value: float = Field(description="HMA value at signal time")
    macd_value: float = Field(description="MACD line value")
    macd_signal: float = Field(description="MACD signal line value")
    macd_histogram: float = Field(description="MACD histogram value")
    close_price: float = Field(description="Triggering candle close price")
    trigger: str = Field(
        description="Indicator that triggered: hull, macd, or confluence"
    )

    def to_vertical_line(self) -> "VerticalLine":
        """Convert this TradeSignal to a VerticalLine for chart rendering."""
        from tastytrade.analytics.visualizations.models import VerticalLine

        return VerticalLine(
            eventSymbol=self.eventSymbol,
            start_time=self.start_time,
            label=self.label,
            color=self.color,
            line_width=self.line_width,
            line_dash=self.line_dash,
            opacity=self.opacity,
            show_label=self.show_label,
            label_font_size=self.label_font_size,
        )
