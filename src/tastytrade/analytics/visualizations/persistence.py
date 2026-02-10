"""InfluxDB persistence for chart annotations."""

import os
from datetime import datetime
from typing import Optional, Union

import pandas as pd
from influxdb_client import InfluxDBClient, Point

from tastytrade.analytics.visualizations.models import (
    BaseAnnotation,
    HorizontalLine,
    VerticalLine,
)

MEASUREMENT = "ChartAnnotation"
DEFAULT_BUCKET = "tastytrade"


def _get_bucket(bucket: Optional[str] = None) -> str:
    return bucket or os.environ.get("INFLUX_DB_BUCKET") or DEFAULT_BUCKET


def annotation_to_point(annotation: BaseAnnotation) -> Point:
    """Serialize a HorizontalLine or VerticalLine to an InfluxDB Point.

    Tags (indexed): symbol, annotation_type, event_type
    Fields: all styling and type-specific attributes
    Timestamp: VerticalLine uses annotation.time; HorizontalLine uses created_at.
    """
    if isinstance(annotation, HorizontalLine):
        annotation_type = "horizontal_line"
    elif isinstance(annotation, VerticalLine):
        annotation_type = "vertical_line"
    else:
        raise TypeError(f"Unsupported annotation type: {type(annotation)}")

    point = Point(MEASUREMENT)
    point.tag("symbol", annotation.symbol)
    point.tag("annotation_type", annotation_type)
    point.tag("event_type", annotation.event_type)

    # Shared styling fields
    point.field("label", annotation.label or "")
    point.field("color", annotation.color)
    point.field("line_width", annotation.line_width)
    point.field("line_dash", annotation.line_dash)
    point.field("opacity", annotation.opacity)
    point.field("show_label", annotation.show_label)
    point.field("label_font_size", annotation.label_font_size)
    point.field("created_at", annotation.created_at.isoformat())

    if isinstance(annotation, HorizontalLine):
        point.field("price", annotation.price)
        point.field("text_position", annotation.text_position)
        point.field("extend_to_end", annotation.extend_to_end)
        point.field(
            "start_time",
            annotation.start_time.isoformat() if annotation.start_time else "",
        )
        point.field(
            "end_time",
            annotation.end_time.isoformat() if annotation.end_time else "",
        )
        point.time(annotation.created_at)
    else:
        assert isinstance(annotation, VerticalLine)
        point.field("text_position", annotation.text_position)
        point.field("text_orientation", annotation.text_orientation)
        point.field("label_padding", annotation.label_padding)
        point.field("span_subplots", annotation.span_subplots)
        point.field("label_bg_opacity", annotation.label_bg_opacity)
        point.time(annotation.time)

    return point


def write_annotations(
    client: InfluxDBClient,
    annotations: list[BaseAnnotation],
    bucket: Optional[str] = None,
) -> int:
    """Write a batch of annotations to InfluxDB.

    Returns the number of annotations written.
    Raises ValueError if any annotation has an empty symbol.
    """
    for ann in annotations:
        if not ann.symbol:
            raise ValueError(
                f"Annotation must have a non-empty symbol for persistence: {ann}"
            )

    points = [annotation_to_point(a) for a in annotations]
    write_api = client.write_api()
    write_api.write(bucket=_get_bucket(bucket), record=points)
    write_api.close()
    return len(points)


def query_annotations(
    client: InfluxDBClient,
    symbol: str,
    lookback_days: int = 30,
    annotation_type: Optional[str] = None,
    event_type: Optional[str] = None,
    bucket: Optional[str] = None,
) -> list[Union[HorizontalLine, VerticalLine]]:
    """Query annotations from InfluxDB and deserialize back to models.

    Args:
        client: InfluxDB client instance.
        symbol: Ticker symbol to filter on.
        lookback_days: How far back to query (default 30 days).
        annotation_type: Optional filter — "horizontal_line" or "vertical_line".
        event_type: Optional filter on the event_type tag.
        bucket: InfluxDB bucket (defaults to INFLUX_DB_BUCKET env var).

    Returns:
        List of HorizontalLine and/or VerticalLine models.
    """
    filters = [
        f'r["_measurement"] == "{MEASUREMENT}"',
        f'r["symbol"] == "{symbol}"',
    ]
    if annotation_type:
        filters.append(f'r["annotation_type"] == "{annotation_type}"')
    if event_type:
        filters.append(f'r["event_type"] == "{event_type}"')

    filter_expr = " and ".join(filters)
    query = f"""
        from(bucket: "{_get_bucket(bucket)}")
          |> range(start: -{lookback_days}d)
          |> filter(fn: (r) => {filter_expr})
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    """

    query_api = client.query_api()
    raw = query_api.query_data_frame(query)

    if isinstance(raw, list):
        raw = pd.concat(raw, ignore_index=True) if raw else pd.DataFrame()

    if raw.empty:
        return []

    results: list[Union[HorizontalLine, VerticalLine]] = []
    for _, row in raw.iterrows():
        ann_type = row.get("annotation_type", "")
        if ann_type == "horizontal_line":
            results.append(_row_to_horizontal(row))
        elif ann_type == "vertical_line":
            results.append(_row_to_vertical(row))

    return results


def _row_to_horizontal(row: pd.Series) -> HorizontalLine:  # type: ignore[type-arg]
    """Deserialize an InfluxDB pivot row into a HorizontalLine model."""
    return HorizontalLine(
        symbol=row.get("symbol", ""),
        event_type=row.get("event_type", "chart_annotation"),
        label=row.get("label", None) or None,
        color=row.get("color", "white"),
        line_width=float(row.get("line_width", 1.0)),
        line_dash=row.get("line_dash", "solid"),
        opacity=float(row.get("opacity", 0.7)),
        show_label=bool(row.get("show_label", True)),
        label_font_size=float(row.get("label_font_size", 11.0)),
        created_at=_parse_dt(row.get("created_at", "")),
        price=float(row["price"]),
        text_position=row.get("text_position", "left"),
        extend_to_end=bool(row.get("extend_to_end", False)),
        start_time=_parse_optional_dt(row.get("start_time", "")),
        end_time=_parse_optional_dt(row.get("end_time", "")),
    )


def _row_to_vertical(row: pd.Series) -> VerticalLine:  # type: ignore[type-arg]
    """Deserialize an InfluxDB pivot row into a VerticalLine model."""
    raw_time = row.get("_time")
    if isinstance(raw_time, pd.Timestamp):
        time_val: datetime = raw_time.to_pydatetime()
    elif isinstance(raw_time, datetime):
        time_val = raw_time
    else:
        raise TypeError(f"Unexpected _time type: {type(raw_time)}")

    return VerticalLine(
        symbol=row.get("symbol", ""),
        event_type=row.get("event_type", "chart_annotation"),
        label=row.get("label", None) or None,
        color=row.get("color", "white"),
        line_width=float(row.get("line_width", 1.0)),
        line_dash=row.get("line_dash", "solid"),
        opacity=float(row.get("opacity", 0.7)),
        show_label=bool(row.get("show_label", True)),
        label_font_size=float(row.get("label_font_size", 11.0)),
        created_at=_parse_dt(row.get("created_at", "")),
        time=time_val,
        text_position=row.get("text_position", "top"),
        text_orientation=row.get("text_orientation", "horizontal"),
        label_padding=int(row.get("label_padding", 6)),
        span_subplots=bool(row.get("span_subplots", True)),
        label_bg_opacity=float(row.get("label_bg_opacity", 0.8)),
    )


def _parse_dt(value: object) -> datetime:
    """Parse an ISO-format string or passthrough a datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    from datetime import UTC

    return datetime.now(UTC)


def _parse_optional_dt(value: object) -> Optional[datetime]:
    """Parse an ISO-format string to datetime, returning None for empty values."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None
