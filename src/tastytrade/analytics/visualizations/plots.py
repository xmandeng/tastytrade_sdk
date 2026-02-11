import io
import os
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional, cast

import plotly.graph_objects as go
import polars as pl
import pytz
from PIL import Image
from PIL.Image import Image as PILImage
from plotly.subplots import make_subplots

from tastytrade.analytics.indicators.momentum import hull
from tastytrade.analytics.visualizations.models import HorizontalLine, VerticalLine

__all__ = ["HorizontalLine", "VerticalLine", "plot_macd_with_hull"]


def plot_macd_with_hull(
    df: pl.DataFrame,
    pad_value: float | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    tz_name: str | None = None,
    horizontal_lines: Optional[List[HorizontalLine]] = None,
    vertical_lines: Optional[List["VerticalLine"]] = None,
    render_to_image: bool = False,
    image_width: int = 1200,
    image_height: int = 800,
    *,
    naive_time_assumption: Literal["utc", "display"] = "utc",
) -> Optional[PILImage]:
    """
    Generate a candlestick chart with Hull Moving Average and MACD.

    Args:
        df: Polars DataFrame with OHLC and MACD data
        pad_value: Value to use for padding calculations
        start_time: Optional start time for x-axis (defaults to earliest data point)
        end_time: Optional end time for x-axis (defaults to latest data point)
        tz_name: Optional timezone name (defaults to TASTYTRADE_CHART_TIMEZONE env var or 'America/New_York')
        horizontal_lines: Optional list of HorizontalLine objects to plot on the chart
        vertical_lines: Optional list of VerticalLine objects to plot on the chart
        render_to_image: If True, returns a PIL Image instead of displaying the plot
        image_width: Width of the output image when render_to_image is True
        image_height: Height of the output image when render_to_image is True

    Returns:
        PIL.Image.Image if render_to_image is True, otherwise None

    Timezone & naive datetime handling overview:
        Historically this function implicitly treated naive datetimes (those with dt.tzinfo is None)
        as UTC by calling dt.replace(tzinfo=UTC). That caused confusing / broken x‑axis ranges when
        a caller passed naive local times (e.g. Eastern) – especially around midnight boundaries
        where the UTC calendar date differs from the local trading session date. This manifested as:
            - Horizontal / vertical lines rendering on an unexpected date
            - Entire chart appearing blank because x_min/x_max no longer overlapped candle data

        We now offer the parameter naive_time_assumption with two options:
            "utc" (default): Backwards compatible – naive times interpreted as UTC
            "display": Naive times are interpreted as times already in the display timezone

        All input times (start/end + line objects) are normalized via _normalize_dt so every
        timestamp on the figure is timezone‑aware and in the display timezone, preventing
        mixed-awareness operations and accidental date shifts.
    """
    # First compute the Hull MA
    hma_study = hull(input_df=df, pad_value=pad_value)

    # Get timezone from parameter, environment, or default to America/New_York
    # Ensure we have a string before calling pytz.timezone()
    timezone_name = (
        tz_name or os.environ.get("TASTYTRADE_CHART_TIMEZONE") or "America/New_York"
    )
    try:
        display_tz = pytz.timezone(timezone_name)
    except pytz.exceptions.UnknownTimeZoneError:
        # Fall back to US Eastern time if timezone is invalid
        display_tz = pytz.timezone("America/New_York")
        print(
            f"Warning: Unknown timezone '{timezone_name}'. Using 'America/New_York' instead."
        )

    # --- Time normalization helpers -----------------------------------------------------------
    def _normalize_dt(dt: Optional[datetime]) -> Optional[datetime]:
        """Return a timezone-aware datetime in the display timezone.

        Rules:
            * None -> None
            * Aware -> convert to display_tz
            * Naive -> interpret according to naive_time_assumption:
                - "utc": treat as UTC clock time
                - "display": treat as already in display timezone
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            if naive_time_assumption == "utc":
                dt = dt.replace(tzinfo=timezone.utc).astimezone(display_tz)
            else:  # display
                # Localize in display timezone *without* converting clock value
                dt = (
                    display_tz.localize(dt)
                    if hasattr(display_tz, "localize")
                    else dt.replace(tzinfo=display_tz)
                )
        else:
            dt = dt.astimezone(display_tz)
        return dt

    def convert_time(dt: Optional[datetime]):  # Backwards compatibility internal alias
        return _normalize_dt(dt)

    # Create timezone-aware copies of dataframes for plotting
    df_plot = df.clone()
    hma_plot = hma_study.clone()

    # Convert time column to target timezone
    df_plot = df_plot.with_columns(
        pl.col("time").dt.replace_time_zone("UTC").dt.convert_time_zone(timezone_name)
    )

    # Convert HMA time column to display timezone (Polars)
    hma_plot = hma_plot.with_columns(
        pl.col("time").dt.replace_time_zone("UTC").dt.convert_time_zone(timezone_name)
    )

    # Determine x-axis range - ensure non-empty and non-None for mypy
    raw_min = df_plot["time"].min()
    raw_max = df_plot["time"].max()
    if raw_min is None or raw_max is None:
        raise ValueError("DataFrame time column has no min/max (empty dataset)")

    # Polars returns datetime objects here
    data_min = cast(datetime, raw_min)
    data_max = cast(datetime, raw_max)

    if start_time is not None:
        norm_start = _normalize_dt(start_time)
        assert norm_start is not None
        x_min: datetime = norm_start
    else:
        x_min = data_min

    if end_time is not None:
        norm_end = _normalize_dt(end_time)
        assert norm_end is not None
        x_max: datetime = norm_end
    else:
        x_max = data_max

    # Helper for numeric extraction
    def _to_float(value: object) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            import numpy as _np  # type: ignore

            if isinstance(value, (_np.integer, _np.floating)):
                return float(value)  # type: ignore[arg-type]
        except Exception:
            pass
        raise TypeError(f"Non-numeric value encountered: {value!r} ({type(value)})")

    low_min_raw = df_plot["low"].min()
    high_max_raw = df_plot["high"].max()
    if low_min_raw is None or high_max_raw is None:
        raise ValueError("OHLC data empty for price range computation")
    price_min = _to_float(low_min_raw)
    price_max = _to_float(high_max_raw)

    hma_min_raw = hma_plot["HMA"].min()
    hma_max_raw = hma_plot["HMA"].max()
    hma_min = _to_float(hma_min_raw)
    hma_max = _to_float(hma_max_raw)

    if hma_min < price_min:
        price_min = hma_min
    if hma_max > price_max:
        price_max = hma_max

    # Adjust min/max to include all horizontal lines
    if horizontal_lines:
        for h_line in horizontal_lines:
            price_min = min(price_min, h_line.price)
            price_max = max(price_max, h_line.price)

    price_range = price_max - price_min
    price_padding = price_range * 0.05  # 5% padding

    # Create the subplots
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.4, 0.2]
    )

    # --- Top subplot: Candlestick chart ---
    fig.add_trace(
        go.Candlestick(
            x=df_plot["time"],
            open=df_plot["open"],
            high=df_plot["high"],
            low=df_plot["low"],
            close=df_plot["close"],
            name="Price",
            showlegend=False,
            increasing_line_color="#4CAF50",  # Green outline for up candles
            decreasing_line_color="#EF5350",  # Red outline for down candles
            increasing_fillcolor="rgba(19, 19, 19, 0.1)",  # Semi-transparent black fill for up candles
            decreasing_fillcolor="#EF5350",  # Semi-transparent red fill for down candles
            line_width=0.75,  # Width of the candlewicks
        ),
        row=1,
        col=1,
    )

    # Create separate traces for each color segment of HMA
    # Convert to pandas at the visualization boundary for Plotly segment rendering
    hma_pdf = hma_plot.to_pandas()
    for i in range(1, len(hma_pdf)):
        fig.add_trace(
            go.Scatter(
                x=hma_pdf["time"].iloc[i - 1 : i + 1],
                y=hma_pdf["HMA"].iloc[i - 1 : i + 1],
                mode="lines",
                line={
                    "color": (
                        "#01FFFF" if hma_pdf["HMA_color"].iloc[i] == "Up" else "#FF66FE"
                    ),
                    "width": 0.6,
                },
                showlegend=False,
                name="HMA",
            ),
            row=1,
            col=1,
        )

    # --- Bottom subplot: MACD Value, Signal, Histogram ---
    fig.add_trace(
        go.Scatter(
            x=df_plot["time"],
            y=df_plot["Value"],
            mode="lines",
            name="MACD (Value)",
            line={"color": "#01FFFF", "width": 1},
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_plot["time"],
            y=df_plot["avg"],
            mode="lines",
            name="Signal (avg)",
            line={"color": "#F8E9A6", "width": 1},
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Histogram bars
    fig.add_trace(
        go.Bar(
            x=df_plot["time"],
            y=df_plot["diff"],
            name="Histogram (diff)",
            marker_color=list(df_plot["diff_color"]),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Zero line for MACD - make sure it spans the full time range
    fig.add_shape(
        type="line",
        x0=x_min,
        x1=x_max,
        y0=0,
        y1=0,
        line={"color": "gray", "width": 1, "dash": "dot"},
        xref="x2",
        yref="y2",
    )

    # Add horizontal lines if provided
    if horizontal_lines:
        for h_line in horizontal_lines:
            # Add the line
            # Determine start and end x-coordinates
            if h_line.extend_to_end:
                x0_val: datetime = x_min
                x1_val: datetime = x_max
            else:
                # Use custom times if provided, otherwise use chart boundaries
                if h_line.start_time:
                    start_dt = _normalize_dt(h_line.start_time)
                    assert start_dt is not None
                    x0_val = start_dt
                else:
                    x0_val = x_min
                if h_line.end_time:
                    end_dt = _normalize_dt(h_line.end_time)
                    assert end_dt is not None
                    x1_val = end_dt
                else:
                    x1_val = x_max

            fig.add_shape(
                type="line",
                x0=x0_val,
                x1=x1_val,
                y0=h_line.price,
                y1=h_line.price,
                line={
                    "color": h_line.color,
                    "width": h_line.line_width,
                    "dash": h_line.line_dash,
                },
                opacity=h_line.opacity,
                xref="x",
                yref="y",
                row=1,
                col=1,
            )

            # Add a label for the line if specified
            if h_line.show_label and h_line.label is not None:
                # Calculate x position based on text_position
                x_pos: datetime
                if h_line.text_position == "left":
                    x_pos = x0_val  # Use line start point for left alignment
                elif h_line.text_position == "right":
                    x_pos = x1_val  # Use line end point for right alignment
                else:  # middle
                    delta_full = x1_val - x0_val
                    delta_half = timedelta(seconds=delta_full.total_seconds() / 2.0)
                    x_pos = x0_val + delta_half

                fig.add_annotation(
                    x=x_pos,
                    y=h_line.price,
                    text=h_line.label,
                    showarrow=False,
                    font={
                        "color": h_line.color,
                        "size": h_line.label_font_size,
                        "family": "Arial, sans-serif",
                    },
                    bgcolor="rgba(25,25,25,0.7)",  # Semi-transparent background
                    bordercolor=h_line.color,
                    borderwidth=1,
                    borderpad=4,
                    xanchor=(
                        "left"
                        if h_line.text_position == "left"
                        else "right"
                        if h_line.text_position == "right"
                        else "center"
                    ),
                    yanchor="bottom",
                    xref="x",
                    yref="y",
                )

    # Calculate y ranges for plots
    y_min_price = price_min - price_padding
    y_max_price = price_max + (price_padding * 2)  # Double padding at top for labels

    # For MACD panel
    diff_min_raw = df_plot["diff"].min()
    value_min_raw = df_plot["Value"].min()
    avg_min_raw = df_plot["avg"].min()
    diff_max_raw = df_plot["diff"].max()
    value_max_raw = df_plot["Value"].max()
    avg_max_raw = df_plot["avg"].max()
    macd_min = (
        min(_to_float(diff_min_raw), _to_float(value_min_raw), _to_float(avg_min_raw))
        * 1.2
    )
    macd_max = (
        max(_to_float(diff_max_raw), _to_float(value_max_raw), _to_float(avg_max_raw))
        * 1.2
    )

    # Add vertical time lines if provided
    if vertical_lines:
        for v_line in vertical_lines:
            # Convert time to display timezone if it has one
            line_time_opt = _normalize_dt(v_line.start_time)
            assert line_time_opt is not None
            line_time: datetime = line_time_opt

            # Add the vertical line to both panels with explicit typing to satisfy mypy
            panel_ranges: list[tuple[int, tuple[float, float]]] = [
                (1, (y_min_price, y_max_price)),
                (2, (macd_min, macd_max)),
            ]
            for row_idx, (y0_panel, y1_panel) in panel_ranges:
                # Skip the second panel if not set to span subplots
                if row_idx == 2 and not v_line.span_subplots:
                    continue

                fig.add_shape(
                    type="line",
                    x0=line_time,
                    x1=line_time,
                    y0=y0_panel,
                    y1=y1_panel,
                    line={
                        "color": v_line.color,
                        "width": v_line.line_width,
                        "dash": v_line.line_dash,
                    },
                    opacity=v_line.opacity,
                    xref=f"x{row_idx}",
                    yref=f"y{row_idx}",
                )

            # Add label only once (on the price chart) if specified and showing labels
            if v_line.show_label and v_line.label is not None:
                # Calculate y position based on text_position with additional padding for top labels
                if v_line.text_position == "top":
                    # Position text at the top of the chart
                    y_pos = y_max_price
                    y_anchor = "bottom"  # Position text above the line
                elif v_line.text_position == "bottom":
                    y_pos = y_min_price
                    y_anchor = "top"  # Position text below the line
                else:  # middle
                    y_pos = (y_min_price + y_max_price) / 2
                    y_anchor = "middle"

                # Set text angle based on orientation
                text_angle = 270 if v_line.text_orientation == "vertical" else 0

                # Add more padding for the label
                # Preserve newlines in labels by setting align="center"
                # Safely construct the background color with the line's opacity value
                bg_opacity = v_line.label_bg_opacity
                bg_color = f"rgba(25,25,25,{bg_opacity})"

                fig.add_annotation(
                    x=line_time,
                    y=y_pos,
                    text=v_line.label,
                    showarrow=False,
                    font={
                        "color": v_line.color,
                        "size": v_line.label_font_size,
                        "family": "Arial, sans-serif",
                    },
                    bgcolor=bg_color,  # Use the pre-constructed background color
                    bordercolor=v_line.color,
                    borderwidth=1,
                    borderpad=v_line.label_padding,  # Increased padding
                    textangle=text_angle,
                    xanchor="center",
                    yanchor=y_anchor,
                    xref="x",
                    yref="y",
                    align="center",  # Enables proper alignment for multi-line text
                )

    # Update layout
    # title_with_tz = f"{event_symbol} w/ HMA-20 ({timezone_name})"
    # Update layout
    # title_with_tz = f"{event_symbol} w/ HMA-20 ({timezone_name})"
    fig.update_layout(
        # title=title_with_tz,
        xaxis2_title="Time",
        yaxis_title="Price",
        yaxis2_title="MACD",
        showlegend=True,
        height=image_height if render_to_image else 800,
        width=image_width if render_to_image else None,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        plot_bgcolor="rgb(25,25,25)",
        paper_bgcolor="rgb(25,25,25)",
        margin={"l": 30, "r": 5, "t": 50, "b": 10},  # Standard top margin
    )

    # Set y-axis range for price chart with padding
    fig.update_yaxes(
        gridcolor="rgba(128,128,128,0.1)",
        zerolinecolor="rgba(128,128,128,0.1)",
        range=[y_min_price, y_max_price],
        row=1,
        col=1,
        ticklabelposition="outside",
        automargin=True,
        ticklen=4,  # Reduced tick length
        tickwidth=1,
        ticks="outside",
        ticksuffix=" ",  # Single space after tick labels
        tickfont={"size": 11},  # Control font size
        showgrid=True,
        zeroline=False,  # Remove zero line to avoid artifacts
        showticklabels=True,
        # Set main tick interval to 20
        dtick=10,
        # Add minor ticks configuration
        minor={
            "ticklen": 2,  # Shorter length for minor ticks
            "tickwidth": 1,
            "tickcolor": "rgba(150,150,150,0.5)",
            "tickmode": "linear",
            "dtick": 5,  # 5-point intervals for minor ticks
            "showgrid": False,
            "ticks": "outside",
        },
    )

    # Normal styling for MACD subplot
    fig.update_yaxes(
        gridcolor="rgba(128,128,128,0.1)",
        zerolinecolor="rgba(128,128,128,0.1)",
        range=[macd_min, macd_max],  # Set explicit range
        row=2,
        col=1,
        side="left",
        ticklabelposition="outside",
        automargin=True,
        ticklen=4,  # Reduced tick length
        tickwidth=1,
        ticks="outside",
        ticksuffix=" ",  # Single space after tick labels
        tickfont={"size": 11},  # Control font size
        showgrid=True,
        zeroline=False,  # Remove zero line to avoid artifacts
        showticklabels=True,
    )

    # Force the xaxis range for both subplots
    fig.update_xaxes(
        gridcolor="rgba(128,128,128,0.1)",
        zerolinecolor="rgba(128,128,128,0.1)",
        range=[x_min, x_max],
        automargin=True,
        # Set 30-minute interval for x-axis ticks
        dtick=30 * 60 * 1000,  # 30 minutes in milliseconds
    )

    if render_to_image:
        # Convert the plotly figure to a PIL Image
        img_bytes = fig.to_image(format="png", width=image_width, height=image_height)
        img = Image.open(io.BytesIO(img_bytes))
        return img
    else:
        fig.show()
        return None
