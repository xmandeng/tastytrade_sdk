import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import clear_output, display

from tastytrade.providers.market import MarketDataProvider

logger = logging.getLogger(__name__)


@dataclass
class Study:
    """Configuration for a technical study overlay."""

    name: str
    compute_fn: Callable
    params: Dict[str, Any]
    plot_params: Dict[str, Any]
    value_column: str
    color_column: Optional[str] = None


class CandleChart:

    def __init__(
        self,
        streamer: MarketDataProvider,
        symbol: str,
        start_time: Optional[pd.Timestamp] = None,
        end_time: Optional[pd.Timestamp] = None,
        chart_style: Optional[Dict[str, Any]] = None,
    ):
        self.stream = streamer
        self.symbol = symbol
        self.start_time = start_time
        self.end_time = end_time
        self.studies: List[Study] = []
        self.task: Optional[asyncio.Task] = None

        self.chart_style = {
            "plot_bgcolor": "rgb(25,25,25)",
            "paper_bgcolor": "rgb(25,25,25)",
            "title": dict(text=symbol, x=0.5, font=dict(color="white", size=16)),
            "yaxis": dict(
                gridcolor="rgba(128,128,128,0.1)",
                zerolinecolor="rgba(128,128,128,0.1)",
                color="white",
            ),
            "xaxis": dict(
                gridcolor="rgba(128,128,128,0.1)",
                zerolinecolor="rgba(128,128,128,0.1)",
                color="white",
            ),
            "showlegend": True,
            "height": 800,
            "uirevision": True,
        }

        if chart_style:
            self.chart_style.update(chart_style)

    def add_study(self, study: Study) -> None:
        self.studies.append(study)

    def remove_study(self, study_name: str) -> None:
        self.studies = [s for s in self.studies if s.name != study_name]

    def create_color_segments(self, df: pd.DataFrame, study: Study) -> List[go.Scatter]:
        """Create separate traces for each color segment with overlapping points for continuity."""
        traces = []
        colors = study.plot_params["colors"]
        df = df.reset_index(drop=True)

        # Find where color changes occur
        df["color"] = df[study.color_column].map(colors)
        color_changes = df["color"] != df["color"].shift()
        change_indices = np.where(color_changes)[0]

        # Handle case where there are no color changes
        if len(change_indices) == 0:
            return [
                go.Scatter(
                    x=df["time"],
                    y=df[study.value_column],
                    line=dict(color=df["color"].iloc[0], width=1),
                    mode="lines",
                    name=study.name,
                    showlegend=True,
                    hoverinfo="y+x",
                )
            ]

        # Create segments with overlap
        segments = []
        start_idx = 0

        for end_idx in change_indices:
            segment_df = df.iloc[start_idx : end_idx + 1]  # Include the change point
            segments.append((segment_df, df["color"].iloc[start_idx]))
            start_idx = end_idx  # Start next segment at the change point

        # Add the last segment
        if start_idx < len(df):
            last_segment_df = df.iloc[start_idx:]
            segments.append((last_segment_df, df["color"].iloc[start_idx]))

        # Create traces
        for i, (segment_df, color) in enumerate(segments):
            traces.append(
                go.Scatter(
                    x=segment_df["time"],
                    y=segment_df[study.value_column],
                    line=dict(color=color, width=1),
                    mode="lines",
                    name=study.name,
                    showlegend=(i == 0),  # Only show in legend for first segment
                    hoverinfo="y+x",
                )
            )

        return traces

    async def update_chart(self) -> None:
        fig = go.Figure()
        fig.update_layout(**self.chart_style)

        try:
            while True:
                assert self.stream is not None
                raw_df = self.stream[self.symbol].to_pandas()

                if len(raw_df) == 0:
                    logger.warning("No data available for symbol %s", self.symbol)
                    break

                plot_df = raw_df.copy()

                # Filter by time range if specified
                if self.start_time:
                    plot_df = plot_df[plot_df["time"] >= self.start_time]
                if self.end_time:
                    plot_df = plot_df[plot_df["time"] <= self.end_time]

                try:
                    with fig.batch_update():
                        fig.data = []

                        # Add candlesticks
                        fig.add_trace(
                            go.Candlestick(
                                x=plot_df["time"],
                                open=plot_df["open"],
                                high=plot_df["high"],
                                low=plot_df["low"],
                                close=plot_df["close"],
                                increasing=dict(line=dict(width=1), fillcolor="#26A69A"),
                                decreasing=dict(line=dict(width=1), fillcolor="#EF5350"),
                                name="Price",
                            )
                        )

                        # Add each study
                        for study in self.studies:
                            study_df = study.compute_fn(
                                self.stream[self.symbol], self.symbol, **study.params
                            )

                            if study.color_column:
                                # Add color-changing segments
                                traces = self.create_color_segments(study_df, study)
                                for trace in traces:
                                    fig.add_trace(trace)
                            else:
                                # Handle single-color studies
                                fig.add_trace(
                                    go.Scatter(
                                        x=study_df["time"],
                                        y=study_df[study.value_column],
                                        line=study.plot_params,
                                        mode="lines",
                                        name=study.name,
                                        showlegend=True,
                                    )
                                )

                    clear_output(wait=True)
                    display(fig)
                    logger.debug("Plot updated successfully")

                except Exception as e:
                    logger.error(f"Error updating plot: {e}")
                    break

        except asyncio.CancelledError:
            logger.debug(f"Stopped plotting {self.symbol}")
        except Exception as e:
            logger.error(f"Unexpected error in chart update: {e}")
            sys.exit(1)

    def start(self) -> asyncio.Task:
        self.task = asyncio.create_task(self.update_chart(), name=f"dynamic_chart_{self.symbol}")
        return self.task

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
