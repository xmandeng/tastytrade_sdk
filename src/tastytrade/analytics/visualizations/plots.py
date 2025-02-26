from datetime import datetime

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from tastytrade.analytics.indicators.momentum import hull


def plot_macd_with_hull(
    df: pl.DataFrame,
    pad_value: float | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> None:
    # First compute the Hull MA
    hma_study = hull(input_df=df, pad_value=pad_value)

    try:
        event_symbol = df["eventSymbol"].unique()[0]
    except Exception:
        event_symbol = "Stock_Symbol"

    # Determine x-axis range - use data range if not specified
    x_min = start_time if start_time is not None else df["time"].min()
    x_max = end_time if end_time is not None else df["time"].max()

    # Create the subplots
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.4, 0.2]
    )

    # --- Top subplot: Candlestick chart ---
    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
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
    for i in range(1, len(hma_study)):
        fig.add_trace(
            go.Scatter(
                x=hma_study["time"].iloc[i - 1 : i + 1],
                y=hma_study["HMA"].iloc[i - 1 : i + 1],
                mode="lines",
                line=dict(
                    color="#01FFFF" if hma_study["HMA_color"].iloc[i] == "Up" else "#FF66FE",
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
            x=df["time"],
            y=df["Value"],
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
            x=df["time"],
            y=df["avg"],
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
            x=df["time"],
            y=df["diff"],
            name="Histogram (diff)",
            marker_color=[color for color in df["diff_color"]],
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
    fig.update_layout(
        title=f"{event_symbol} w/ HMA-20",
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
