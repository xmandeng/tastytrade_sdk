"""Chart annotation models backed by BaseEvent for native InfluxDB persistence."""

from datetime import UTC, datetime
from typing import Annotated, Optional, Union

from pydantic import BeforeValidator, Field

from tastytrade.messaging.models.events import BaseEvent


def _coerce_price(v: Union[float, int, None]) -> float:
    """Accept float, int, or None — coerce int to float, reject None."""
    if v is None:
        raise ValueError("price cannot be None for HorizontalLine")
    return float(v)


class BaseAnnotation(BaseEvent):
    """Base for all chart annotation events with shared styling fields.

    Extends BaseEvent so annotations flow through the same InfluxDB
    processor pipeline as CandleEvent, TradeEvent, etc.
    """

    eventSymbol: str = Field(
        default="", description="Symbol this annotation is associated with"
    )
    event_type: str = "chart_annotation"
    label: Optional[str] = None
    color: str = "white"
    line_width: float = 1.0
    line_dash: str = "solid"
    opacity: float = Field(default=0.7, ge=0.0, le=1.0)
    show_label: bool = True
    label_font_size: float = 11.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HorizontalLine(BaseAnnotation):
    """A horizontal price level line on a chart."""

    price: Annotated[float, BeforeValidator(_coerce_price)]
    text_position: str = "left"
    extend_to_end: bool = False
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class VerticalLine(BaseAnnotation):
    """A vertical time line on a chart."""

    time: datetime
    text_position: str = "top"
    text_orientation: str = "horizontal"
    label_padding: int = 6
    span_subplots: bool = True
    label_bg_opacity: float = 0.8
