import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import clear_output, display
from plotly.subplots import make_subplots

from tastytrade.connections.sockets import Channels, DXLinkManager
from tastytrade.providers.market import MarketDataProvider

logger = logging.getLogger(__name__)


@dataclass
class Study:
    """Enhanced configuration for technical study overlays."""

    name: str
    compute_fn: Callable
    params: Dict[str, Any]
    plot_params: Dict[str, Any]
    value_columns: Union[str, List[str]]  # Support single column or multiple columns
    color_column: Optional[str] = None
    subplot_config: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        # Convert single column to list for consistent handling
        if isinstance(self.value_columns, str):
            self.value_columns = [self.value_columns]

    def compute(
        self,
        market_provider: MarketDataProvider,
        symbol: str,
        input_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Compute study values using provider."""
        return self.compute_fn(
            market_provider=market_provider, symbol=symbol, input_df=input_df, **self.params
        )


class DynamicChart:
    def __init__(
        self,
        dxlink: DXLinkManager,
        market_provider: MarketDataProvider,
        symbol: str,
        start_time: Optional[pd.Timestamp] = None,
        end_time: Optional[pd.Timestamp] = None,
        chart_style: Optional[Dict[str, Any]] = None,
    ):
        self.dxlink = dxlink
        self.market_provider = market_provider
        self.symbol = symbol

        # Ensure timestamps are in UTC
        self.start_time = self.ensure_utc(start_time)
        self.end_time = self.ensure_utc(end_time)

        logger.debug(
            f"Initialized chart with start_time: {self.start_time}, end_time: {self.end_time}"
        )

        self.studies: List[Study] = []
        self.task: Optional[asyncio.Task] = None

        # Default chart style
        self.chart_style = {
            "template": "plotly_dark",
            "plot_bgcolor": "rgb(25,25,25)",
            "paper_bgcolor": "rgb(25,25,25)",
            "title": dict(text=symbol, x=0.5, font=dict(color="white", size=16)),
            "height": 800,
            "uirevision": True,
            "margin": dict(l=50, r=50, t=30, b=50),
        }

        if chart_style:
            self.chart_style.update(chart_style)

    def ensure_utc(self, timestamp: Optional[pd.Timestamp]) -> Optional[pd.Timestamp]:
        """Ensure timestamp is in UTC."""
        if timestamp is None:
            return None

        if not isinstance(timestamp, pd.Timestamp):
            timestamp = pd.Timestamp(timestamp)

        if timestamp.tz is None:
            timestamp = timestamp.tz_localize("UTC")
        elif timestamp.tzinfo is not None and timestamp.tzinfo.tzname(None) != "UTC":
            timestamp = timestamp.tz_convert("UTC")

        return timestamp

    def normalize_dataframe_times(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize DataFrame timestamps to UTC."""
        if "time" not in df.columns:
            return df

        df = df.copy()

        # Convert time column to pandas timestamp if it's not already
        if not pd.api.types.is_datetime64_any_dtype(df["time"]):
            df["time"] = pd.to_datetime(df["time"])

        # Ensure timezone is UTC
        if df["time"].dt.tz is None:
            df["time"] = df["time"].dt.tz_localize("UTC")
        else:
            df["time"] = df["time"].dt.tz_convert("UTC")

        return df

    async def ensure_data_available(self) -> None:
        """Ensure historical and live data are available."""
        if self.symbol not in self.market_provider:
            logger.debug(f"Retrieving historical data for {self.symbol}")

            # Convert start_time to datetime, using current time if None
            start = (
                self.start_time.to_pydatetime() if self.start_time is not None else datetime.now()
            )

            # Initialize historical data
            self.market_provider.retrieve(
                symbol=self.symbol,
                event_type="CandleEvent",
                start=start,
                stop=self.end_time.to_pydatetime() if self.end_time is not None else None,
            )

            # Setup live updates
            logger.debug(f"Setting up live updates for {self.symbol}")
            await self.market_provider.subscribe(self.symbol)

    def create_figure(self) -> go.Figure:
        """Create figure with subplots based on studies."""
        # Calculate subplot heights
        study_count = len([s for s in self.studies if s.subplot_config])
        subplot_height = 0.2 if study_count > 0 else 0
        main_height = 1 - (subplot_height * study_count)

        # Create subplot specs
        specs = [[{"secondary_y": True}] for _ in range(study_count + 1)]

        # Create figure
        fig = make_subplots(
            rows=study_count + 1,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.02,
            row_heights=[main_height] + [subplot_height] * study_count,
            specs=specs,
        )

        # Apply base style
        fig.update_layout(**self.chart_style)

        return fig

    def create_color_segments(
        self, df: pd.DataFrame, study: Study, value_column: str
    ) -> List[go.Scatter]:
        """Create separate traces for each color segment with overlapping points."""
        df = self.normalize_dataframe_times(df)
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
                    y=df[value_column],
                    line=dict(color=df["color"].iloc[0], width=1),
                    mode="lines",
                    name=f"{study.name} ({value_column})",
                    showlegend=True,
                    hoverinfo="y+x",
                )
            ]

        # Create segments with overlap
        segments = []
        start_idx = 0

        for end_idx in change_indices:
            segment_df = df.iloc[start_idx : end_idx + 1]
            segments.append((segment_df, df["color"].iloc[start_idx]))
            start_idx = end_idx

        # Add the last segment
        if start_idx < len(df):
            last_segment_df = df.iloc[start_idx:]
            segments.append((last_segment_df, df["color"].iloc[start_idx]))

        # Create traces
        for i, (segment_df, color) in enumerate(segments):
            traces.append(
                go.Scatter(
                    x=segment_df["time"],
                    y=segment_df[value_column],
                    line=dict(color=color, width=1),
                    mode="lines",
                    name=f"{study.name} ({value_column})",
                    showlegend=(i == 0),
                    hoverinfo="y+x",
                )
            )

        return traces

    def update_candlesticks(self, fig: go.Figure, data: pd.DataFrame, row: int = 1) -> None:
        """Update candlestick chart."""
        data = self.normalize_dataframe_times(data)
        fig.add_trace(
            go.Candlestick(
                x=data["time"],
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
                increasing=dict(line=dict(width=1), fillcolor="#26A69A"),
                decreasing=dict(line=dict(width=1), fillcolor="#EF5350"),
                name="Price",
            ),
            row=row,
            col=1,
        )

    def update_study(self, fig: go.Figure, study: Study, data: pd.DataFrame, row: int) -> None:
        """Update study traces."""
        data = self.normalize_dataframe_times(data)
        try:
            study_df = study.compute(self.market_provider, self.symbol, input_df=data)
            study_df = self.normalize_dataframe_times(study_df)

            for value_column in study.value_columns:
                if study.color_column:
                    traces = self.create_color_segments(study_df, study, value_column)
                    for trace in traces:
                        fig.add_trace(trace, row=row, col=1)
                else:
                    fig.add_trace(
                        go.Scatter(
                            x=study_df["time"],
                            y=study_df[value_column],
                            line=study.plot_params,
                            mode="lines",
                            name=f"{study.name} ({value_column})",
                            showlegend=True,
                        ),
                        row=row,
                        col=1,
                    )
        except Exception as e:
            logger.error(f"Error updating study {study.name}: {e}")
            raise

    async def update_chart(self) -> None:
        """Update chart with latest data."""
        try:
            await self.ensure_data_available()
            fig = self.create_figure()

            while True:
                raw_df = self.market_provider[self.symbol].to_pandas()

                if len(raw_df) == 0:
                    logger.warning("No data available for symbol %s", self.symbol)
                    await asyncio.sleep(1)
                    continue

                plot_df = self.normalize_dataframe_times(raw_df.copy())

                # Debug timestamp information
                logger.debug(f"Time column dtype: {plot_df['time'].dtype}")
                logger.debug(
                    f"Time column timezone: {plot_df['time'].dt.tz if hasattr(plot_df['time'].dt, 'tz') else 'None'}"
                )
                logger.debug(f"Start time: {self.start_time}, dtype: {type(self.start_time)}")
                logger.debug(f"End time: {self.end_time}, dtype: {type(self.end_time)}")

                # Filter by time range if specified
                if self.start_time:
                    plot_df = plot_df[plot_df["time"] >= self.start_time]
                if self.end_time:
                    plot_df = plot_df[plot_df["time"] <= self.end_time]

                try:
                    with fig.batch_update():
                        fig.data = []

                        # Update main chart
                        self.update_candlesticks(fig, plot_df, row=1)

                        # Update studies
                        current_row = 2
                        for study in self.studies:
                            if study.subplot_config:
                                self.update_study(fig, study, plot_df, row=current_row)
                                current_row += 1
                            else:
                                self.update_study(fig, study, plot_df, row=1)

                        # Ensure x-axis covers full timeframe
                        if self.start_time and self.end_time:
                            fig.update_xaxes(range=[self.start_time, self.end_time])

                    clear_output(wait=True)
                    display(fig)
                    logger.debug("Plot updated successfully")

                except Exception as e:
                    logger.error(f"Error updating plot: {e}")
                    raise

                await self.dxlink.queues[Channels.Candle.value].get()

        except asyncio.CancelledError:
            logger.debug(f"Stopped plotting {self.symbol}")
        except Exception as e:
            logger.error(f"Unexpected error in chart update: {e}", exc_info=True)
            raise

    def add_study(self, study: Study) -> None:
        """Add a study to the chart."""
        self.studies.append(study)

    def remove_study(self, study_name: str) -> None:
        """Remove a study from the chart."""
        self.studies = [s for s in self.studies if s.name != study_name]

    def start(self) -> asyncio.Task:
        """Start chart updates."""
        self.task = asyncio.create_task(self.update_chart(), name=f"dynamic_chart_{self.symbol}")
        return self.task

    async def stop(self) -> None:
        """Stop chart updates."""
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
