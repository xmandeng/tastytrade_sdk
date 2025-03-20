import io
import os
from datetime import datetime, timezone
from typing import List, Optional

import plotly.graph_objects as go
import polars as pl
import pytz
from PIL import Image
from PIL.Image import Image as PILImage
from plotly.subplots import make_subplots

from tastytrade.analytics.indicators.momentum import hull


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
        text_orientation: str = "horizontal",  # "horizontal", "vertical"
        label_padding: int = 6,  # Increased default padding for labels
        span_subplots: bool = True,  # Span both price and MACD panels
        label_bg_opacity: float = 0.8,  # Control background opacity for better visibility
    ):
        """
        Initialize a vertical time line.

        Args:
            time: The x-value (datetime) where the line will be drawn
            label: Optional text label for the line (None to display no label)
            color: Color of the line (name, hex, or rgb)
            line_width: Width of the line in pixels
            line_dash: Line style ("solid", "dot", "dash", "longdash", "dashdot", "longdashdot")
            opacity: Opacity of the line (0.0 to 1.0)
            text_position: Position of the label ("top", "middle", "bottom")
            show_label: Whether to display the label text
            label_font_size: Font size for the label
            text_orientation: Orientation of label text ("horizontal", "vertical")
            label_padding: Padding space around the label in pixels
            span_subplots: Whether the line should span across all subplots
            label_bg_opacity: Control background opacity for better visibility
        """
        self.time = time
        # Default label is None (optional) instead of using the time
        self.label = label
        self.color = color
        self.line_width = line_width
        self.line_dash = line_dash
        self.opacity = opacity
        self.text_position = text_position
        self.show_label = show_label
        self.label_font_size = label_font_size
        self.text_orientation = text_orientation
        self.label_padding = label_padding
        self.span_subplots = span_subplots
        self.label_bg_opacity = label_bg_opacity


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

    # Determine x-axis range - use data range if not specified
    x_min = convert_time(start_time) if start_time is not None else df_plot["time"].min()
    x_max = convert_time(end_time) if end_time is not None else df_plot["time"].max()

    # Calculate price range for y-axis limits including horizontal lines
    price_min = df_plot["low"].min()
    price_max = df_plot["high"].max()

    # Also consider HMA values for y-axis range
    hma_min = hma_plot["HMA"].min()
    hma_max = hma_plot["HMA"].max()

    # Take the minimum of price_min and hma_min
    price_min = min(price_min, hma_min)
    price_max = max(price_max, hma_max)

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

    # Calculate y ranges for plots
    y_min_price = price_min - price_padding
    y_max_price = price_max + (price_padding * 2)  # Double padding at top for labels

    # For MACD panel, get data-driven min/max
    macd_min = min(df_plot["diff"].min(), df_plot["Value"].min(), df_plot["avg"].min()) * 1.2
    macd_max = max(df_plot["diff"].max(), df_plot["Value"].max(), df_plot["avg"].max()) * 1.2

    # Add vertical time lines if provided
    if vertical_lines:
        for i, v_line in enumerate(vertical_lines):
            # Convert time to display timezone if it has one
            line_time = v_line.time
            if line_time.tzinfo is None:
                line_time = line_time.replace(tzinfo=timezone.utc)
            line_time = line_time.astimezone(display_tz)

            # Add the vertical line to both panels
            for row_idx, y_range in [(1, [y_min_price, y_max_price]), (2, [macd_min, macd_max])]:
                # Skip the second panel if not set to span subplots
                if row_idx == 2 and not v_line.span_subplots:
                    continue

                fig.add_shape(
                    type="line",
                    x0=line_time,
                    x1=line_time,
                    y0=y_range[0],
                    y1=y_range[1],
                    line=dict(
                        color=v_line.color,
                        width=v_line.line_width,
                        dash=v_line.line_dash,
                    ),
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
                    font=dict(
                        color=v_line.color, size=v_line.label_font_size, family="Arial, sans-serif"
                    ),
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
        margin=dict(l=30, r=5, t=50, b=10),  # Standard top margin
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
        tickfont=dict(size=11),  # Control font size
        showgrid=True,
        zeroline=False,  # Remove zero line to avoid artifacts
        showticklabels=True,
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
