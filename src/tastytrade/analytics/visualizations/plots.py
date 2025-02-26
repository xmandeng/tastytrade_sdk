import os
from datetime import datetime, timezone

import plotly.graph_objects as go
import polars as pl
import pytz
from plotly.subplots import make_subplots

from tastytrade.analytics.indicators.momentum import hull


def plot_macd_with_hull(
    df: pl.DataFrame,
    pad_value: float | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    tz_name: str | None = None,
) -> None:
    """
    Generate a candlestick chart with Hull Moving Average and MACD.

    Args:
        df: Polars DataFrame with OHLC and MACD data
        pad_value: Value to use for padding calculations
        start_time: Optional start time for x-axis (defaults to earliest data point)
        end_time: Optional end time for x-axis (defaults to latest data point)
        tz_name: Optional timezone name (defaults to TASTYTRADE_CHART_TIMEZONE env var or 'America/New_York')
    """
    # First compute the Hull MA
    hma_study = hull(input_df=df, pad_value=pad_value)

    # Get timezone from parameter, environment, or default to America/New_York
    # Ensure we have a string before calling pytz.timezone()
    timezone_name = tz_name or os.environ.get("TASTYTRADE_CHART_TIMEZONE") or "America/New_York"
    try:
        display_tz = pytz.timezone(timezone_name)
    except pytz.exceptions.UnknownTimeZoneError:
        # Fall back to US Eastern time if timezone is invalid
        display_tz = pytz.timezone("America/New_York")
        print(f"Warning: Unknown timezone '{timezone_name}'. Using 'America/New_York' instead.")

    # Convert times to the specified timezone
    def convert_time(dt):
        if dt is None:
            return None
        # Ensure datetime has a timezone if it doesn't
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(display_tz)

    # Create timezone-aware copies of dataframes for plotting
    df_plot = df.clone()
    hma_plot = hma_study.copy()

    # Convert time column to target timezone
    df_plot = df_plot.with_columns(
        pl.col("time").dt.replace_time_zone("UTC").dt.convert_time_zone(timezone_name)
    )

    # For pandas DataFrame (hma_study)
    hma_plot["time"] = hma_plot["time"].dt.tz_localize("UTC").dt.tz_convert(timezone_name)

    try:
        event_symbol = df["eventSymbol"].unique()[0]
    except Exception:
        event_symbol = "Stock_Symbol"

    # Determine x-axis range - use data range if not specified
    x_min = convert_time(start_time) if start_time is not None else df_plot["time"].min()
    x_max = convert_time(end_time) if end_time is not None else df_plot["time"].max()

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
    for i in range(1, len(hma_plot)):
        fig.add_trace(
            go.Scatter(
                x=hma_plot["time"].iloc[i - 1 : i + 1],
                y=hma_plot["HMA"].iloc[i - 1 : i + 1],
                mode="lines",
                line=dict(
                    color="#01FFFF" if hma_plot["HMA_color"].iloc[i] == "Up" else "#FF66FE",
                    width=0.6,
                ),
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
            line=dict(color="#01FFFF", width=1),
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
            line=dict(color="#F8E9A6", width=1),
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
            marker_color=[color for color in df_plot["diff_color"]],
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
        line=dict(color="gray", width=1, dash="dot"),
        xref="x2",
        yref="y2",
    )

    # Update layout
    title_with_tz = f"{event_symbol} w/ HMA-20 ({timezone_name})"
    fig.update_layout(
        title=title_with_tz,
        xaxis2_title="Time",
        yaxis_title="Price",
        yaxis2_title="MACD",
        showlegend=True,
        height=800,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        plot_bgcolor="rgb(25,25,25)",
        paper_bgcolor="rgb(25,25,25)",
    )

    fig.update_yaxes(gridcolor="rgba(128,128,128,0.1)", zerolinecolor="rgba(128,128,128,0.1)")

    # Force the xaxis range for both subplots
    fig.update_xaxes(
        gridcolor="rgba(128,128,128,0.1)",
        zerolinecolor="rgba(128,128,128,0.1)",
        range=[x_min, x_max],
    )

    fig.show()
