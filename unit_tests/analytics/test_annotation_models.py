"""Tests for chart annotation models backed by BaseEvent."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tastytrade.analytics.visualizations.models import (
    BaseAnnotation,
    HorizontalLine,
    VerticalLine,
)
from tastytrade.messaging.models.events import BaseEvent

# .time adds a deterministic microsecond jitter (0-999 us) for InfluxDB uniqueness.
_MAX_JITTER = timedelta(microseconds=999)


def test_annotations_are_base_events() -> None:
    """Annotations must be BaseEvent subclasses for processor compatibility."""
    now = datetime.now(UTC)
    h = HorizontalLine(price=100.0, start_time=now, label="support")
    v = VerticalLine(start_time=now, label="entry")
    assert isinstance(h, BaseEvent)
    assert isinstance(v, BaseEvent)
    assert isinstance(h, BaseAnnotation)
    assert isinstance(v, BaseAnnotation)


def test_horizontal_line_minimal() -> None:
    """Construct with required fields; verify defaults and .time property."""
    now = datetime.now(UTC)
    h = HorizontalLine(price=520.50, start_time=now, label="support")
    assert h.price == 520.50
    assert h.start_time == now
    assert now <= h.time <= now + _MAX_JITTER
    assert h.label == "support"
    assert h.color == "white"
    assert h.line_width == 1.0
    assert h.line_dash == "solid"
    assert h.opacity == 0.7
    assert h.text_position == "left"
    assert h.show_label is True
    assert h.label_font_size == 11.0
    assert h.extend_to_end is False
    assert h.end_time is None
    assert h.eventSymbol == ""
    assert h.event_type == "chart_annotation"


def test_vertical_line_minimal() -> None:
    """Construct with required fields; verify defaults and .time property."""
    now = datetime.now(UTC)
    v = VerticalLine(start_time=now, label="entry")
    assert v.start_time == now
    assert now <= v.time <= now + _MAX_JITTER
    assert v.label == "entry"
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
    assert v.eventSymbol == ""
    assert v.event_type == "chart_annotation"


def test_vertical_line_accepts_time_kwarg() -> None:
    """Backward compat: VerticalLine(time=dt) remaps to start_time."""
    now = datetime.now(UTC)
    v = VerticalLine(time=now, label="entry")  # type: ignore[call-arg]
    assert v.start_time == now
    assert now <= v.time <= now + _MAX_JITTER


def test_horizontal_line_all_fields() -> None:
    """Construct with all fields including eventSymbol and event_type."""
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
        eventSymbol="SPY",
        event_type="price_level",
    )
    assert h.price == 100.0
    assert h.eventSymbol == "SPY"
    assert h.event_type == "price_level"
    assert h.color == "cyan"
    assert h.line_width == 2.0
    assert h.opacity == 0.9
    assert h.start_time == ts
    assert h.end_time == ts
    assert ts <= h.time <= ts + _MAX_JITTER


def test_frozen_immutability() -> None:
    """Frozen models should reject attribute assignment."""
    now = datetime.now(UTC)
    h = HorizontalLine(price=100.0, start_time=now, label="support")
    with pytest.raises(ValidationError):
        h.price = 200.0  # type: ignore[misc]

    v = VerticalLine(start_time=now, label="entry")
    with pytest.raises(ValidationError):
        v.color = "red"  # type: ignore[misc]


def test_horizontal_line_rejects_none_price() -> None:
    """price is required and cannot be None."""
    with pytest.raises(ValidationError):
        HorizontalLine(price=None, start_time=datetime.now(UTC), label="x")  # type: ignore[arg-type]


def test_label_is_required() -> None:
    """label must be provided — it drives the InfluxDB timestamp jitter."""
    with pytest.raises(ValidationError):
        HorizontalLine(price=100.0, start_time=datetime.now(UTC))  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        VerticalLine(start_time=datetime.now(UTC))  # type: ignore[call-arg]


def test_opacity_validation() -> None:
    """Opacity outside [0.0, 1.0] should be rejected."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        HorizontalLine(price=100.0, start_time=now, label="x", opacity=1.5)

    with pytest.raises(ValidationError):
        HorizontalLine(price=100.0, start_time=now, label="x", opacity=-0.1)

    # Boundary values should work
    h_zero = HorizontalLine(price=100.0, start_time=now, label="x", opacity=0.0)
    assert h_zero.opacity == 0.0
    h_one = HorizontalLine(price=100.0, start_time=now, label="x", opacity=1.0)
    assert h_one.opacity == 1.0


def test_processor_compatible_dict() -> None:
    """Annotations must expose fields via __dict__ for the InfluxDB processor.

    Datetime values must be converted to ISO strings during iteration,
    and None values must be skipped.
    """
    ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    h = HorizontalLine(
        price=520.50,
        eventSymbol="SPX",
        event_type="support_level",
        start_time=ts,
        label="support",
    )
    d = h.__dict__

    # Direct access returns raw types
    assert d["eventSymbol"] == "SPX"
    assert d["price"] == 520.50
    assert d["event_type"] == "support_level"
    assert isinstance(d["start_time"], datetime)
    assert "color" in d

    # Iteration converts datetimes to ISO strings and skips None
    items = dict(d.items())
    assert items["start_time"] == ts.isoformat()
    assert isinstance(items["start_time"], str)
    assert "end_time" not in items  # None values are skipped

    # All iterated values must be processor-compatible types
    for key, value in d.items():
        assert isinstance(
            value, (str, int, float, bool)
        ), f"Field {key!r} has non-primitive type {type(value).__name__}: {value!r}"


def test_processor_safe_iteration() -> None:
    """Verify __dict__.items() yields only primitive types for all annotation types."""
    ts = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    v = VerticalLine(start_time=ts, eventSymbol="AAPL", label="entry")
    for key, value in v.__dict__.items():
        assert isinstance(
            value, (str, int, float, bool)
        ), f"VerticalLine field {key!r} has type {type(value).__name__}"

    h = HorizontalLine(
        price=150.0, start_time=ts, end_time=ts, eventSymbol="AAPL", label="level"
    )
    for key, value in h.__dict__.items():
        assert isinstance(
            value, (str, int, float, bool)
        ), f"HorizontalLine field {key!r} has type {type(value).__name__}"


def test_model_copy_preserves_processor_safety() -> None:
    """model_copy must re-wrap __dict__ so copies are also processor-safe."""
    ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    h = HorizontalLine(price=100.0, start_time=ts, eventSymbol="SPX", label="support")
    copy = h.model_copy(update={"eventSymbol": "AAPL"})

    assert copy.eventSymbol == "AAPL"
    assert copy.start_time == ts  # direct access returns datetime

    # Iteration on the copy must also be safe
    for key, value in copy.__dict__.items():
        assert isinstance(
            value, (str, int, float, bool)
        ), f"Copied field {key!r} has type {type(value).__name__}"


def test_time_property_not_in_dict() -> None:
    """The `time` property must NOT appear in __dict__ (avoids processor field loop)."""
    ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    v = VerticalLine(start_time=ts, label="entry")
    assert "time" not in v.__dict__
    assert hasattr(v, "time")  # but accessible as property
    assert ts <= v.time <= ts + _MAX_JITTER


def test_time_jitter_is_deterministic() -> None:
    """Same annotation content must produce the same .time offset every call."""
    ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    v = VerticalLine(start_time=ts, label="Open", color="#555555")
    assert v.time == v.time  # same object, same result


def test_time_jitter_differentiates_annotations() -> None:
    """Annotations with same start_time but different labels get unique .time values."""
    ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    h1 = HorizontalLine(price=100.0, start_time=ts, label="prior close")
    h2 = HorizontalLine(price=200.0, start_time=ts, label="prior high")
    h3 = HorizontalLine(price=300.0, start_time=ts, label="prior low")

    times = {h1.time, h2.time, h3.time}
    assert len(times) == 3, f"Expected 3 unique times, got {len(times)}: {times}"
