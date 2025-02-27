import os
from datetime import datetime, timezone
from typing import List, Optional

import plotly.graph_objects as go
import polars as pl
import pytz
from plotly.subplots import make_subplots

from tastytrade.analytics.indicators.momentum import hull

# # Forward reference to avoid circular imports
# if TYPE_CHECKING:
#     from tastytrade.analytics.visualizations.plots import VerticalLine


class HorizontalLine:
    """Class representing a horizontal line to be plotted on a chart."""

    def __init__(
        self,
        price: float,
        label: Optional[str] = None,
        color: str = "white",
        line_width: float = 1.0,
        line_dash: str = "solid",
        opacity: float = 0.7,
        text_position: str = "left",
        show_label: bool = True,
        label_font_size: int = 11,
        extend_to_end: bool = False,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ):
        """
        Initialize a horizontal line.

        Args:
            price: The y-value (price) where the line will be drawn
            label: Optional text label for the line (None to display no label)
            color: Color of the line (name, hex, or rgb)
            line_width: Width of the line in pixels
            line_dash: Line style ("solid", "dot", "dash", "longdash", "dashdot", "longdashdot")
            opacity: Opacity of the line (0.0 to 1.0)
            text_position: Position of the label ("left", "middle", "right")
            show_label: Whether to display the label text
            label_font_size: Font size for the label
            extend_to_end: Whether the line should extend to the full width of the chart
            start_time: Optional custom start time for the line (if None, uses chart min time)
            end_time: Optional custom end time for the line (if None, uses chart max time)
        """
        self.price = price
        self.label = label  # Allow None value without providing a default
        self.color = color
        self.line_width = line_width
        self.line_dash = line_dash
        self.opacity = opacity
        self.text_position = text_position
        self.show_label = show_label
        self.label_font_size = label_font_size
        self.extend_to_end = extend_to_end
        self.start_time = start_time
        self.end_time = end_time


class VerticalLine:
    """Class representing a vertical time line to be plotted on a chart."""

    def __init__(
        self,
        time: datetime,
        label: Optional[str] = None,
        color: str = "white",
        line_width: float = 1.0,
        line_dash: str = "solid",
        opacity: float = 0.7,
        text_position: str = "top",  # "top", "middle", "bottom"
        show_label: bool = True,
        label_font_size: int = 11,
    ):
        """
        Initialize a vertical time line.

        Args:
            time: The x-value (datetime) where the line will be drawn
            label: Optional text label for the line
            color: Color of the line (name, hex, or rgb)
            line_width: Width of the line in pixels
            line_dash: Line style ("solid", "dot", "dash", "longdash", "dashdot", "longdashdot")
            opacity: Opacity of the line (0.0 to 1.0)
            text_position: Position of the label ("top", "middle", "bottom")
            show_label: Whether to display the label text
            label_font_size: Font size for the label
        """
        self.time = time
        self.label = label if label else time.strftime("%H:%M")
        self.color = color
        self.line_width = line_width
        self.line_dash = line_dash
        self.opacity = opacity
        self.text_position = text_position
        self.show_label = show_label
        self.label_font_size = label_font_size


def plot_macd_with_hull(
    df: pl.DataFrame,
    pad_value: float | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    tz_name: str | None = None,
    horizontal_lines: Optional[List[HorizontalLine]] = None,
    vertical_lines: Optional[List["VerticalLine"]] = None,
) -> None:
    """
    Generate a candlestick chart with Hull Moving Average and MACD.

    Args:
        df: Polars DataFrame with OHLC and MACD data
        pad_value: Value to use for padding calculations
        start_time: Optional start time for x-axis (defaults to earliest data point)
        end_time: Optional end time for x-axis (defaults to latest data point)
        tz_name: Optional timezone name (defaults to TASTYTRADE_CHART_TIMEZONE env var or 'America/New_York')
        horizontal_lines: Optional list of HorizontalLine objects to plot on the chart
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

    # Calculate price range for y-axis limits including horizontal lines
    price_min = df_plot["low"].min()
    price_max = df_plot["high"].max()

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

    # Add horizontal lines if provided
    if horizontal_lines:
        for i, h_line in enumerate(horizontal_lines):
            # Add the line
            # Determine start and end x-coordinates
            if h_line.extend_to_end:
                x0_val = x_min
                x1_val = x_max
            else:
                # Use custom times if provided, otherwise use chart boundaries
                x0_val = convert_time(h_line.start_time) if h_line.start_time else x_min
                x1_val = convert_time(h_line.end_time) if h_line.end_time else x_max

            fig.add_shape(
                type="line",
                x0=x0_val,
                x1=x1_val,
                y0=h_line.price,
                y1=h_line.price,
                line=dict(
                    color=h_line.color,
                    width=h_line.line_width,
                    dash=h_line.line_dash,
                ),
                opacity=h_line.opacity,
                xref="x",
                yref="y",
                row=1,
                col=1,
            )

            # Add a label for the line if specified
            if h_line.show_label and h_line.label is not None:
                # Calculate x position based on text_position
                if h_line.text_position == "left":
                    x_pos = x0_val  # Use line start point for left alignment
                elif h_line.text_position == "right":
                    x_pos = x1_val  # Use line end point for right alignment
                else:  # middle
                    x_pos = x0_val + (x1_val - x0_val) / 2  # Midpoint of the line

                fig.add_annotation(
                    x=x_pos,
                    y=h_line.price,
                    text=h_line.label,
                    showarrow=False,
                    font=dict(
                        color=h_line.color, size=h_line.label_font_size, family="Arial, sans-serif"
                    ),
                    bgcolor="rgba(25,25,25,0.7)",  # Semi-transparent background
                    bordercolor=h_line.color,
                    borderwidth=1,
                    borderpad=4,
                    xanchor=(
                        "left"
                        if h_line.text_position == "left"
                        else "right" if h_line.text_position == "right" else "center"
                    ),
                    yanchor="bottom",
                    xref="x",
                    yref="y",
                )

    # Add vertical time lines if provided
    if vertical_lines:
        # Calculate y range for price chart
        y_min = price_min - price_padding
        y_max = price_max + price_padding

        for i, v_line in enumerate(vertical_lines):
            # Convert time to display timezone if it has one
            line_time = v_line.time
            if line_time.tzinfo is None:
                line_time = line_time.replace(tzinfo=timezone.utc)
            line_time = line_time.astimezone(display_tz)

            # Add the vertical line (for both the price chart and MACD)
            for row_idx, y_range in [(1, [y_min, y_max]), (2, None)]:
                # For MACD panel (row 2), we need to get data-driven min/max
                if row_idx == 2:
                    macd_min = df_plot["diff"].min() * 1.1
                    macd_max = df_plot["Value"].max() * 1.1
                    y_range = [macd_min, macd_max]

                fig.add_shape(
                    type="line",
                    x0=line_time,
                    x1=line_time,
                    y0=y_range[0] if y_range else None,
                    y1=y_range[1] if y_range else None,
                    line=dict(
                        color=v_line.color,
                        width=v_line.line_width,
                        dash=v_line.line_dash,
                    ),
                    opacity=v_line.opacity,
                    xref="x",
                    yref="y",
                    row=row_idx,
                    col=1,
                )

            # Add label only once (on the price chart)
            if v_line.show_label and v_line.label:
                # Calculate y position based on text_position
                if v_line.text_position == "top":
                    y_pos = y_max
                    y_anchor = "top"
                elif v_line.text_position == "bottom":
                    y_pos = y_min
                    y_anchor = "bottom"
                else:  # middle
                    y_pos = (y_min + y_max) / 2
                    y_anchor = "middle"

                fig.add_annotation(
                    x=line_time,
                    y=y_pos,
                    text=v_line.label,
                    showarrow=False,
                    font=dict(
                        color=v_line.color, size=v_line.label_font_size, family="Arial, sans-serif"
                    ),
                    bgcolor="rgba(25,25,25,0.7)",  # Semi-transparent background
                    bordercolor=v_line.color,
                    borderwidth=1,
                    borderpad=3,
                    textangle=270,  # Vertical text
                    xanchor="center",
                    yanchor=y_anchor,
                    xref="x",
                    yref="y",
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
        margin=dict(l=30, r=5, t=50, b=10),  # Reduced left margin to 30px
    )

    # Set y-axis range for price chart with padding
    fig.update_yaxes(
        gridcolor="rgba(128,128,128,0.1)",
        zerolinecolor="rgba(128,128,128,0.1)",
        range=[price_min - price_padding, price_max + price_padding],
        row=1,
        col=1,
        ticklabelposition="outside",
        automargin=True,
        ticklen=4,  # Reduced tick length
        tickwidth=1,
        ticks="outside",
        ticksuffix=" ",  # Single space after tick labels
        tickfont=dict(size=11),  # Control font size
        showgrid=True,
        zeroline=False,  # Remove zero line to avoid artifacts
        showticklabels=True,
    )

    # Normal styling for MACD subplot
    fig.update_yaxes(
        gridcolor="rgba(128,128,128,0.1)",
        zerolinecolor="rgba(128,128,128,0.1)",
        row=2,
        col=1,
        side="left",
        ticklabelposition="outside",
        automargin=True,
        ticklen=4,  # Reduced tick length
        tickwidth=1,
        ticks="outside",
        ticksuffix=" ",  # Single space after tick labels
        tickfont=dict(size=11),  # Control font size
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
    )

    fig.show()
