"""Tests for chart annotation InfluxDB persistence (AC2, AC5)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tastytrade.analytics.visualizations.models import HorizontalLine, VerticalLine
from tastytrade.analytics.visualizations.persistence import (
    _row_to_horizontal,
    _row_to_vertical,
    annotation_to_point,
    write_annotations,
    query_annotations,
)


def test_annotation_to_point_vertical() -> None:
    """Verify tags, fields, and timestamp on a VerticalLine Point."""
    t = datetime(2026, 2, 5, 14, 30, 0, tzinfo=timezone.utc)
    v = VerticalLine(
        time=t,
        symbol="SPY",
        event_type="order_fill",
        label="BUY 100",
        color="green",
        line_width=2.0,
        opacity=0.9,
    )
    point = annotation_to_point(v)
    line = point.to_line_protocol()

    assert "ChartAnnotation" in line
    assert "symbol=SPY" in line
    assert "annotation_type=vertical_line" in line
    assert "event_type=order_fill" in line
    assert 'label="BUY 100"' in line
    assert 'color="green"' in line
    assert "line_width=2" in line
    assert "opacity=0.9" in line
    assert 'text_orientation="horizontal"' in line
    assert "span_subplots=true" in line or "span_subplots=True" in line


def test_annotation_to_point_horizontal() -> None:
    """Verify tags, fields, and timestamp on a HorizontalLine Point."""
    created = datetime(2026, 2, 5, 12, 0, 0, tzinfo=timezone.utc)
    start = datetime(2026, 2, 5, 9, 30, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 5, 16, 0, 0, tzinfo=timezone.utc)
    h = HorizontalLine(
        price=520.50,
        symbol="SPY",
        event_type="price_level",
        label="support",
        start_time=start,
        end_time=end,
        created_at=created,
    )
    point = annotation_to_point(h)
    line = point.to_line_protocol()

    assert "ChartAnnotation" in line
    assert "symbol=SPY" in line
    assert "annotation_type=horizontal_line" in line
    assert "event_type=price_level" in line
    assert "price=520.5" in line
    assert 'label="support"' in line
    assert "extend_to_end=false" in line or "extend_to_end=False" in line


def test_write_annotations_rejects_empty_symbol() -> None:
    """write_annotations should raise ValueError if symbol is empty."""
    client = MagicMock()
    h = HorizontalLine(price=100.0)  # symbol defaults to ""
    with pytest.raises(ValueError, match="non-empty symbol"):
        write_annotations(client, [h])


def test_row_to_horizontal_round_trip() -> None:
    """Serialize a HorizontalLine to Point then deserialize from a row; fields must match."""
    created = datetime(2026, 2, 5, 12, 0, 0, tzinfo=timezone.utc)
    start = datetime(2026, 2, 5, 9, 30, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 5, 16, 0, 0, tzinfo=timezone.utc)
    original = HorizontalLine(
        price=520.50,
        symbol="SPY",
        event_type="price_level",
        label="support",
        color="cyan",
        line_width=2.0,
        line_dash="dash",
        opacity=0.8,
        show_label=True,
        label_font_size=12.0,
        text_position="right",
        extend_to_end=True,
        start_time=start,
        end_time=end,
        created_at=created,
    )

    # Simulate the row that InfluxDB pivot would return
    row = pd.Series(
        {
            "_time": pd.Timestamp(created),
            "symbol": "SPY",
            "annotation_type": "horizontal_line",
            "event_type": "price_level",
            "label": "support",
            "color": "cyan",
            "line_width": 2.0,
            "line_dash": "dash",
            "opacity": 0.8,
            "show_label": True,
            "label_font_size": 12.0,
            "text_position": "right",
            "extend_to_end": True,
            "price": 520.50,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "created_at": created.isoformat(),
        }
    )

    restored = _row_to_horizontal(row)
    assert restored.price == original.price
    assert restored.symbol == original.symbol
    assert restored.event_type == original.event_type
    assert restored.label == original.label
    assert restored.color == original.color
    assert restored.line_width == original.line_width
    assert restored.line_dash == original.line_dash
    assert restored.opacity == original.opacity
    assert restored.show_label == original.show_label
    assert restored.label_font_size == original.label_font_size
    assert restored.text_position == original.text_position
    assert restored.extend_to_end == original.extend_to_end
    assert restored.start_time == original.start_time
    assert restored.end_time == original.end_time
    assert restored.created_at == original.created_at


def test_row_to_vertical_round_trip() -> None:
    """Serialize a VerticalLine to Point then deserialize from a row; fields must match."""
    t = datetime(2026, 2, 5, 14, 30, 0, tzinfo=timezone.utc)
    created = datetime(2026, 2, 5, 12, 0, 0, tzinfo=timezone.utc)
    original = VerticalLine(
        time=t,
        symbol="SPY",
        event_type="order_fill",
        label="BUY 100",
        color="green",
        line_width=2.0,
        line_dash="dot",
        opacity=0.9,
        show_label=True,
        label_font_size=10.0,
        text_position="top",
        text_orientation="vertical",
        label_padding=8,
        span_subplots=False,
        label_bg_opacity=0.6,
        created_at=created,
    )

    row = pd.Series(
        {
            "_time": pd.Timestamp(t),
            "symbol": "SPY",
            "annotation_type": "vertical_line",
            "event_type": "order_fill",
            "label": "BUY 100",
            "color": "green",
            "line_width": 2.0,
            "line_dash": "dot",
            "opacity": 0.9,
            "show_label": True,
            "label_font_size": 10.0,
            "text_position": "top",
            "text_orientation": "vertical",
            "label_padding": 8,
            "span_subplots": False,
            "label_bg_opacity": 0.6,
            "created_at": created.isoformat(),
        }
    )

    restored = _row_to_vertical(row)
    assert restored.time == original.time
    assert restored.symbol == original.symbol
    assert restored.event_type == original.event_type
    assert restored.label == original.label
    assert restored.color == original.color
    assert restored.line_width == original.line_width
    assert restored.line_dash == original.line_dash
    assert restored.opacity == original.opacity
    assert restored.show_label == original.show_label
    assert restored.label_font_size == original.label_font_size
    assert restored.text_position == original.text_position
    assert restored.text_orientation == original.text_orientation
    assert restored.label_padding == original.label_padding
    assert restored.span_subplots == original.span_subplots
    assert restored.label_bg_opacity == original.label_bg_opacity
    assert restored.created_at == original.created_at


def test_query_annotations_empty_result() -> None:
    """Mock empty query response; should return empty list."""
    client = MagicMock()
    client.query_api.return_value.query_data_frame.return_value = pd.DataFrame()

    result = query_annotations(client, symbol="SPY", lookback_days=7)
    assert result == []
