import asyncio
import logging
from datetime import datetime
from typing import Optional

import plotly.graph_objects as go
from IPython.display import clear_output, display

from tastytrade.config.enumerations import Channels
from tastytrade.connections.sockets import DXLinkManager

logger = logging.getLogger(__name__)


def plot_live_candlesticks(
    dxlink: DXLinkManager, symbol: str, start_time: datetime, end_time: Optional[datetime] = None
):
    """Live candlestick chart that updates based on the most recent data.

    Args:
        dxlink: DXLink manager instance
        symbol: Symbol to plot (e.g. "BTC/USD:CXTALP{=5m}")
        start_time: Start time for the data to be plotted
        end_time: Optional end time for the data to be plotted
    """
    fig = go.Figure()

    # Set up the figure style
    fig.update_layout(
        plot_bgcolor="rgb(25,25,25)",
        paper_bgcolor="rgb(25,25,25)",
        title=dict(text=symbol, x=0.5, font=dict(color="white", size=16)),
        yaxis=dict(
            gridcolor="rgba(128,128,128,0.1)", zerolinecolor="rgba(128,128,128,0.1)", color="white"
        ),
        xaxis=dict(
            gridcolor="rgba(128,128,128,0.1)", zerolinecolor="rgba(128,128,128,0.1)", color="white"
        ),
        showlegend=False,
    )

    async def update_chart():
        try:
            while True:
                # Get data
                raw_df = (
                    dxlink.router.handler[Channels.Candle]
                    .processors["feed"]
                    .df.loc[lambda x: x["eventSymbol"] == symbol]
                )

                # Filter data based on start and end time
                raw_df = raw_df.loc[lambda x: x["time"] >= start_time]
                if end_time:
                    raw_df = raw_df.loc[lambda x: x["time"] <= end_time]

                logger.debug(f"Got dataframe with {len(raw_df)} rows")

                if len(raw_df) == 0:
                    logger.warning("No data available for symbol %s", symbol)
                    await asyncio.sleep(1)
                    continue

                # Convert timestamps to EDT
                plot_df = raw_df.copy()
                plot_df["time"] = (
                    plot_df["time"].dt.tz_localize("UTC").dt.tz_convert("America/New_York")
                )

                # Update the candlesticks
                try:
                    with fig.batch_update():
                        fig.data = []
                        fig.add_trace(
                            go.Candlestick(
                                x=plot_df["time"],
                                open=plot_df["open"],
                                high=plot_df["high"],
                                low=plot_df["low"],
                                close=plot_df["close"],
                                increasing=dict(line=dict(width=1), fillcolor="#26A69A"),
                                decreasing=dict(line=dict(width=1), fillcolor="#EF5350"),
                            )
                        )

                    clear_output(wait=True)
                    display(fig)
                    logger.debug("Plot updated successfully")

                except Exception as e:
                    logger.error(f"Error updating plot: {e}")

                # Wait for next update
                await dxlink.queues[Channels.Candle.value].get()

        except asyncio.CancelledError:
            logger.debug(f"Stopped plotting {symbol}")
        except Exception as e:
            logger.error(f"Unexpected error in chart update: {e}")

    return asyncio.create_task(update_chart(), name=f"candlestick_plot_{symbol}")
