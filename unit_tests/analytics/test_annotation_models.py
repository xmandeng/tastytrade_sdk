"""Tests for chart annotation Pydantic models (AC1, AC5)."""

from datetime import UTC, datetime, timezone

import pytest
from pydantic import ValidationError

from tastytrade.analytics.visualizations.models import (
    HorizontalLine,
    VerticalLine,
)


def test_horizontal_line_minimal() -> None:
    """Construct with just price; verify all defaults are populated."""
    h = HorizontalLine(price=520.50)
    assert h.price == 520.50
    assert h.label is None
    assert h.color == "white"
    assert h.line_width == 1.0
    assert h.line_dash == "solid"
    assert h.opacity == 0.7
    assert h.text_position == "left"
    assert h.show_label is True
    assert h.label_font_size == 11.0
    assert h.extend_to_end is False
    assert h.start_time is None
    assert h.end_time is None
    assert h.symbol == ""
    assert h.event_type == "chart_annotation"
    assert h.created_at is not None


def test_vertical_line_minimal() -> None:
    """Construct with just time; verify all defaults are populated."""
    now = datetime.now(UTC)
    v = VerticalLine(time=now)
    assert v.time == now
    assert v.label is None
    assert v.color == "white"
    assert v.line_width == 1.0
    assert v.line_dash == "solid"
    assert v.opacity == 0.7
    assert v.text_position == "top"
    assert v.show_label is True
    assert v.label_font_size == 11.0
    assert v.text_orientation == "horizontal"
    assert v.label_padding == 6
    assert v.span_subplots is True
    assert v.label_bg_opacity == 0.8
    assert v.symbol == ""
    assert v.event_type == "chart_annotation"


def test_horizontal_line_all_fields() -> None:
    """Construct with all fields including persistence fields."""
    ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    h = HorizontalLine(
        price=100.0,
        label="support",
        color="cyan",
        line_width=2.0,
        line_dash="dash",
        opacity=0.9,
        text_position="right",
        show_label=False,
        label_font_size=14.0,
        extend_to_end=True,
        start_time=ts,
        end_time=ts,
        symbol="SPY",
        event_type="price_level",
        created_at=ts,
    )
    assert h.price == 100.0
    assert h.symbol == "SPY"
    assert h.event_type == "price_level"
    assert h.color == "cyan"
    assert h.line_width == 2.0
    assert h.opacity == 0.9
    assert h.created_at == ts
    assert h.start_time == ts
    assert h.end_time == ts


def test_frozen_immutability() -> None:
    """Frozen models should reject attribute assignment."""
    h = HorizontalLine(price=100.0)
    with pytest.raises(ValidationError):
        h.price = 200.0  # type: ignore[misc]

    v = VerticalLine(time=datetime.now(UTC))
    with pytest.raises(ValidationError):
        v.color = "red"  # type: ignore[misc]


def test_horizontal_line_rejects_none_price() -> None:
    """price is required and cannot be None."""
    with pytest.raises(ValidationError):
        HorizontalLine(price=None)  # type: ignore[arg-type]


def test_default_created_at() -> None:
    """created_at should auto-populate with a UTC datetime."""
    before = datetime.now(UTC)
    h = HorizontalLine(price=50.0)
    after = datetime.now(UTC)
    assert before <= h.created_at <= after
    assert h.created_at.tzinfo is not None


def test_opacity_validation() -> None:
    """Opacity outside [0.0, 1.0] should be rejected."""
    with pytest.raises(ValidationError):
        HorizontalLine(price=100.0, opacity=1.5)

    with pytest.raises(ValidationError):
        HorizontalLine(price=100.0, opacity=-0.1)

    # Boundary values should work
    h_zero = HorizontalLine(price=100.0, opacity=0.0)
    assert h_zero.opacity == 0.0
    h_one = HorizontalLine(price=100.0, opacity=1.0)
    assert h_one.opacity == 1.0
