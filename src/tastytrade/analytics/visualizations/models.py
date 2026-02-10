"""Pydantic models for chart annotations persisted to InfluxDB."""

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BaseAnnotation(BaseModel):
    """Base model for all chart annotations with shared styling and metadata fields."""

    model_config = ConfigDict(frozen=True, validate_assignment=True, extra="forbid")

    symbol: str = ""
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

    price: float
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
