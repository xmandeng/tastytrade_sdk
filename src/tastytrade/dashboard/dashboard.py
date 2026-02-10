from __future__ import annotations

import asyncio
import logging
from queue import Queue
from threading import Lock, Thread
from typing import Any, List, Optional, Tuple, cast

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, ctx, dcc, html
from dash.dependencies import ALL, Input, Output, State

from tastytrade.analytics.indicators.momentum import hull
from tastytrade.config import RedisConfigManager
from tastytrade.config.enumerations import Channels
from tastytrade.connections import Credentials
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.utils.helpers import (
    last_weekday,
)  # corrected import path for trade day helper

from .types import Component, Figure

logger = logging.getLogger(__name__)


class DashApp:
    def __init__(self) -> None:
        self.app: Dash = Dash(
            __name__,
            external_stylesheets=[dbc.themes.DARKLY],
            title="Live Charts",
            update_title="",
        )
        self.dxlink: Optional[DXLinkManager] = None
        self.subscription_queue: Queue[Tuple[str, str]] = (
            Queue()
        )  # Queue of (symbol, interval) tuples
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.df_lock = Lock()  # Add lock for DataFrame access
        self._chart_lock = asyncio.Lock()  # Add lock for chart updates
        self.setup_layout()
        self.setup_callbacks()

    def setup_layout(self) -> None:
        self.app.layout = self._create_layout()

    def _create_layout(self) -> Component:
        return dbc.Container(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.H1("Live Charts", className="text-center mb-4"),
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            [
                                                dbc.Input(
                                                    id="symbol-input",
                                                    placeholder="Enter symbol (e.g. SPX)",
                                                    type="text",
                                                    className="me-2",
                                                ),
                                            ],
                                            width=6,
                                        ),
                                        dbc.Col(
                                            [
                                                dbc.Select(
                                                    id="interval-select",
                                                    options=[
                                                        {
                                                            "label": "1 minute",
                                                            "value": "1m",
                                                        },
                                                        {
                                                            "label": "5 minutes",
                                                            "value": "5m",
                                                        },
                                                        {
                                                            "label": "15 minutes",
                                                            "value": "15m",
                                                        },
                                                        {
                                                            "label": "30 minutes",
                                                            "value": "30m",
                                                        },
                                                        {
                                                            "label": "1 hour",
                                                            "value": "1h",
                                                        },
                                                    ],
                                                    value="5m",
                                                    className="me-2",
                                                ),
                                            ],
                                            width=3,
                                        ),
                                        dbc.Col(
                                            [
                                                dbc.Button(
                                                    "Add Chart",
                                                    id="add-chart-button",
                                                    color="primary",
                                                    className="w-100",
                                                ),
                                            ],
                                            width=3,
                                        ),
                                    ],
                                    className="g-2 align-items-center",
                                ),
                            ],
                            width=12,
                        )
                    ]
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [html.Div(id="charts-container", children=[])],
                            width=12,
                        )
                    ],
                    className="mt-4",
                ),
            ],
            fluid=True,
            className="py-4",
        )

    async def subscribe_to_symbol(self, symbol: str, interval: str = "5m") -> None:
        """Subscribe to symbol data feeds."""
        if not self.dxlink:
            logger.error("DXLink not initialized")
            return

        try:
            # Convert 1m to m for DXLink subscription while keeping original interval for display
            dxlink_interval = "m" if interval == "1m" else interval

            # Format the symbol for candles using the original interval for filtering
            candle_symbol = f"{symbol}{{={interval}}}"
            logger.debug(f"Starting subscription process for symbol: {symbol}")

            # Hardcode the start time to be 9:30AM on the trade day (today or most recent business day)
            start_time = last_weekday()
            logger.debug(f"Using start time for subscription: {start_time}")

            # Subscribe to candles with base symbol and converted interval
            logger.debug(
                f"Subscribing to candles for {symbol} with interval {dxlink_interval}"
            )
            await self.dxlink.subscribe_to_candles(
                symbol=symbol,
                interval=dxlink_interval,
                from_time=start_time,
            )
            logger.debug("Successfully subscribed to candles")

            # Subscribe to regular symbol updates with base symbol
            logger.debug(f"Subscribing to symbol updates for {symbol}")
            await self.dxlink.subscribe([symbol])
            logger.debug("Successfully subscribed to symbol updates")

            # Wait for initial data with timeout
            max_retries = 10  # Increase retries
            retry_delay = 0.5  # Increase delay to 500ms
            for attempt in range(max_retries):
                if (
                    self.dxlink.router
                    and self.dxlink.router.handler[Channels.Candle].processors
                ):
                    processor = self.dxlink.router.handler[Channels.Candle].processors[
                        "feed"
                    ]
                    try:
                        df = processor.df
                        if df is not None:
                            logger.debug(f"Raw data columns: {df.columns.tolist()}")
                            logger.debug(f"Total rows in raw data: {len(df)}")
                            if not df.empty:
                                logger.debug(
                                    f"Available symbols in raw data: {df['eventSymbol'].unique()}"
                                )
                                # Check for our specific candle symbol
                                symbol_data = df[df["eventSymbol"] == candle_symbol]
                                if not symbol_data.empty:
                                    logger.debug(
                                        f"Found {len(symbol_data)} candles for {candle_symbol}"
                                    )
                                    logger.debug(
                                        f"Sample candle data:\n{symbol_data.head(1).to_dict('records')}"
                                    )
                                    break
                                else:
                                    logger.debug(
                                        f"No data found for {candle_symbol} in current data"
                                    )
                    except Exception as e:
                        logger.debug(
                            f"Attempt {attempt + 1}: Waiting for data... ({str(e)})"
                        )
                await asyncio.sleep(retry_delay)
            else:
                logger.warning(
                    f"No data received for {candle_symbol} after {max_retries} attempts"
                )

        except Exception:
            logger.error(f"Error subscribing to feeds for {symbol}")
            raise

    def process_subscription_queue(self) -> None:
        """Process subscription requests from the queue."""
        logger.debug("Starting subscription queue processor")
        while True:
            try:
                if self.loop is None:
                    logger.warning("No event loop available, waiting...")
                    continue

                logger.debug("Waiting for symbol from queue...")
                symbol, interval = self.subscription_queue.get()
                logger.debug(
                    f"Got symbol from queue: {symbol} with interval: {interval}"
                )

                future = asyncio.run_coroutine_threadsafe(
                    self.subscribe_to_symbol(symbol, interval), self.loop
                )
                # Wait for the subscription to complete
                future.result()

                self.subscription_queue.task_done()
                logger.debug(f"Successfully processed subscription for {symbol}")
            except Exception as e:
                logger.error(f"Error processing subscription queue: {e}", exc_info=True)

    def setup_callbacks(self) -> None:
        @self.app.callback(
            Output("charts-container", "children"),
            [Input("add-chart-button", "n_clicks")],
            [
                State("symbol-input", "value"),
                State("interval-select", "value"),
                State("charts-container", "children"),
            ],
            prevent_initial_call=True,
        )
        def add_chart(
            n_clicks: Optional[int],
            symbol: Optional[str],
            interval: Optional[str],
            existing_charts: Optional[List[Component]],
        ) -> List[Component]:
            logger.debug("Add chart callback triggered")
            if not symbol:
                logger.warning("No symbol provided")
                return existing_charts or []

            symbol = symbol.upper()
            # Convert interval at the start - use "m" instead of "1m" for DXLink
            interval = "m" if interval == "1m" else (interval or "5m")
            logger.debug(f"Processing symbol: {symbol} with interval: {interval}")

            # Check if chart already exists
            if existing_charts:
                chart_id = f"chart-card-{symbol}-{interval}"
                for chart in existing_charts:
                    if chart["props"]["id"] == chart_id:
                        logger.debug(
                            f"Chart for {symbol} with {interval} interval already exists"
                        )
                        return existing_charts

            # Queue the subscription request
            if self.dxlink:
                logger.debug(f"Queueing subscription for {symbol}")
                self.subscription_queue.put((symbol, interval))
            else:
                logger.error("DXLink not initialized!")

            logger.debug(f"Creating chart card for {symbol}")
            new_chart = self._create_chart_card(symbol, interval)

            if existing_charts is None:
                return [new_chart]
            return existing_charts + [new_chart]

        @self.app.callback(
            Output({"type": "chart", "symbol": ALL, "interval": ALL}, "figure"),
            [
                Input(
                    {"type": "interval", "symbol": ALL, "interval": ALL}, "n_intervals"
                ),
                Input(
                    {"type": "interval-slow", "symbol": ALL, "interval": ALL},
                    "n_intervals",
                ),
            ],
            prevent_initial_call=False,
        )
        def update_charts(
            n_intervals: List[int], n_intervals_slow: List[int]
        ) -> List[Figure]:
            logger.debug("Update charts callback triggered")
            logger.debug(
                f"Intervals: {n_intervals}, Slow intervals: {n_intervals_slow}"
            )
            logger.debug(f"Triggered by: {ctx.triggered_id}")
            logger.debug(f"Input list: {ctx.inputs_list}")

            if not ctx.triggered_id:
                logger.debug("No trigger ID in update_charts callback")
                return [
                    self.create_initial_figure(
                        cast(dict[str, Any], props["id"])["symbol"]
                    )
                    for props in ctx.inputs_list[0]
                ]

            figures = []
            try:
                # First, safely get a copy of all the data we'll need
                if not self.dxlink or not self.dxlink.router:
                    logger.warning("DXLink or router not initialized")
                    return [
                        self.create_initial_figure(
                            cast(dict[str, Any], props["id"])["symbol"]
                        )
                        for props in ctx.inputs_list[0]
                    ]

                # Get a snapshot of the candle data
                with self.df_lock:
                    processor = self.dxlink.router.handler[Channels.Candle].processors[
                        "feed"
                    ]
                    logger.debug("Checking processor state")
                    logger.debug(f"Processor type: {type(processor)}")
                    logger.debug(f"Processor has data: {processor.df is not None}")
                    candle_data = (
                        processor.df.copy()
                        if processor.df is not None
                        else pd.DataFrame()
                    )

                if candle_data.empty:
                    logger.warning("No candle data available")
                    return [
                        self.create_initial_figure(
                            cast(dict[str, Any], props["id"])["symbol"]
                        )
                        for props in ctx.inputs_list[0]
                    ]

                logger.debug(f"Candle data shape: {candle_data.shape}")
                logger.debug(f"Candle data columns: {candle_data.columns.tolist()}")
                logger.debug(
                    f"Available symbols in candle data: {candle_data['eventSymbol'].unique()}"
                )

                # Now process each symbol using our copied data
                for interval_props in ctx.inputs_list[0]:
                    props_id = cast(dict[str, Any], interval_props["id"])
                    symbol = props_id["symbol"]
                    interval = props_id["interval"]
                    candle_symbol = f"{symbol}{{={interval}}}"
                    logger.debug(f"Processing chart update for {candle_symbol}")

                    try:
                        # Filter data using exact match with formatted symbol
                        symbol_data = candle_data[
                            candle_data["eventSymbol"] == candle_symbol
                        ].copy()

                        if symbol_data.empty:
                            logger.warning(f"No data found for {candle_symbol}")
                            figures.append(self.create_initial_figure(symbol))
                            continue

                        logger.debug(
                            f"Found {len(symbol_data)} candles for {candle_symbol}"
                        )
                        logger.debug(f"First candle: {symbol_data.iloc[0].to_dict()}")
                        logger.debug(f"Last candle: {symbol_data.iloc[-1].to_dict()}")

                        # Process the data and create the figure
                        figure = self._create_figure_from_data(
                            symbol, symbol_data, interval
                        )
                        logger.debug(
                            f"Figure created for {candle_symbol} with {len(figure.data)} traces"
                        )
                        figures.append(figure)

                    except Exception as e:
                        logger.error(f"Error updating figure for {candle_symbol}: {e}")
                        figures.append(self.create_initial_figure(symbol))

                logger.debug(f"Generated {len(figures)} figures")
                return figures

            except Exception as e:
                logger.error(f"Error in update_charts callback: {e}")
                return [self.create_initial_figure("Error") for _ in ctx.inputs_list[0]]

        @self.app.callback(
            Output("charts-container", "children", allow_duplicate=True),
            [Input({"type": "close-chart", "symbol": ALL}, "n_clicks")],
            [State("charts-container", "children")],
            prevent_initial_call=True,
        )
        def remove_chart(
            n_clicks: List[Optional[int]], existing_charts: List[Component]
        ) -> List[Component]:
            if not ctx.triggered_id:
                return existing_charts

            symbol = cast(dict[str, Any], ctx.triggered_id)["symbol"]
            return [
                chart
                for chart in existing_charts
                if chart["props"]["id"] != f"chart-card-{symbol}"
            ]

    def _create_chart_card(self, symbol: str, interval: str = "5m") -> Component:
        chart_id = f"chart-card-{symbol}-{interval}"
        # Convert "m" to "1m" for display only
        display_interval = "1m" if interval == "m" else interval
        return html.Div(
            id=chart_id,
            children=[
                html.H3(f"{symbol} {display_interval}"),
                dcc.Graph(
                    id={"type": "chart", "symbol": symbol, "interval": interval},
                    figure=self.create_initial_figure(symbol),
                    config={"displayModeBar": True},  # Show the mode bar for debugging
                ),
                # Fast interval for initial updates
                dcc.Interval(
                    id={"type": "interval", "symbol": symbol, "interval": interval},
                    interval=50,  # 50ms for faster initial updates
                    n_intervals=0,
                    max_intervals=100,  # More attempts to catch initial data
                    disabled=False,  # Ensure interval is enabled
                ),
                # Slow interval for regular updates
                dcc.Interval(
                    id={
                        "type": "interval-slow",
                        "symbol": symbol,
                        "interval": interval,
                    },
                    interval=500,  # 500ms for more frequent regular updates
                    n_intervals=0,
                    disabled=False,  # Ensure interval is enabled
                ),
            ],
            style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"},
        )

    def create_initial_figure(self, symbol: str) -> Figure:
        """Create an initial loading figure."""
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            showlegend=True,
            xaxis_rangeslider_visible=False,
            height=600,
            margin={"l": 50, "r": 50, "t": 30, "b": 50},
            yaxis={"title": None},
            xaxis={"title": None},
            title={"text": f"{symbol} Loading...", "x": 0.5, "y": 0.95},
            annotations=[
                {
                    "text": "Loading data...",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": 20, "color": "white"},
                }
            ],
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            uirevision=True,  # Maintain zoom level on updates
        )
        return fig

    def _create_figure_from_data(
        self, symbol: str, df: pd.DataFrame, interval: str = "5m"
    ) -> Figure:
        """Create a figure from pre-filtered DataFrame."""
        try:
            if df.empty:
                logger.warning("Empty DataFrame passed to _create_figure_from_data")
                return self.create_initial_figure(symbol)

            logger.debug(f"Creating figure from DataFrame with shape: {df.shape}")
            logger.debug(f"DataFrame columns: {df.columns.tolist()}")
            logger.debug(f"First row of data:\n{df.iloc[0].to_dict()}")
            logger.debug(f"Last row of data:\n{df.iloc[-1].to_dict()}")

            try:
                # Convert time column from Unix milliseconds to datetime
                df["time"] = pd.to_datetime(df["time"], unit="ms")
                logger.debug(f"Time range: {df['time'].min()} to {df['time'].max()}")
            except KeyError:
                logger.warning("No time column found in data")
                return self.create_initial_figure(symbol)
            except Exception as e:
                logger.warning(f"Error converting time: {e}")
                return self.create_initial_figure(symbol)

            # Only filter rows where OHLC values are NaN since they're critical
            df = df.dropna(subset=["open", "high", "low", "close"])
            valid_rows = len(df)

            if valid_rows == 0:
                logger.warning("No valid OHLC data after dropna")
                return self.create_initial_figure(symbol)

            logger.debug(
                f"OHLC data sample (first row):\n{df[['time', 'open', 'high', 'low', 'close']].iloc[0].to_dict()}"
            )
            logger.debug(
                f"OHLC data sample (last row):\n{df[['time', 'open', 'high', 'low', 'close']].iloc[-1].to_dict()}"
            )

            # Calculate HMA using the formatted symbol
            candle_symbol = f"{symbol}{{={interval}}}"
            hma_df = pd.DataFrame()  # Default to empty DataFrame

            if self.dxlink is not None:
                try:
                    logger.debug(f"Calculating HMA for {candle_symbol}")
                    # Pass the formatted symbol to hull() since it expects that format
                    # Calculate HMA using the existing data instead of passing df as a parameter
                    hma_df = hull(self.dxlink, candle_symbol, length=20)  # type: ignore[arg-type]
                    if not hma_df.empty:
                        logger.debug(
                            f"HMA calculation successful, shape: {hma_df.shape}"
                        )
                        logger.debug(
                            f"HMA sample:\n{hma_df.head(1).to_dict('records')}"
                        )
                        logger.debug(f"HMA columns: {hma_df.columns.tolist()}")
                    else:
                        logger.warning("HMA calculation returned empty DataFrame")
                except Exception as e:
                    logger.warning(f"Error calculating HMA: {e}")
                    logger.error("Full HMA calculation error:")

            if not hma_df.empty:
                hma_df["time"] = pd.to_datetime(hma_df["time"])
                merged_df = pd.merge(df, hma_df, on="time", how="left")
                logger.debug(f"Merged DataFrame shape: {merged_df.shape}")
                logger.debug(f"Merged columns: {merged_df.columns.tolist()}")
            else:
                merged_df = df
                logger.debug("Using DataFrame without HMA")

            # Create figure
            fig = go.Figure()

            # Add candlesticks
            fig.add_trace(
                go.Candlestick(
                    x=merged_df["time"],
                    open=merged_df["open"],
                    high=merged_df["high"],
                    low=merged_df["low"],
                    close=merged_df["close"],
                    name=f"{symbol} Price",
                    increasing_line_color="#26A69A",  # Green
                    decreasing_line_color="#EF5350",  # Red
                )
            )

            # Add HMA if we have it
            if not hma_df.empty:
                fig.add_trace(
                    go.Scatter(
                        x=merged_df["time"],
                        y=merged_df["HMA"],
                        line={"color": "purple", "width": 2},
                        name=f"{symbol} HMA-20",
                    )
                )

            # Update layout
            fig.update_layout(
                template="plotly_dark",
                showlegend=True,
                xaxis_rangeslider_visible=False,
                height=600,
                margin={"l": 50, "r": 50, "t": 30, "b": 50},
                yaxis={"title": None},  # Remove y-axis label
                xaxis={"title": None},  # Remove x-axis label
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )

            logger.debug(f"Successfully created figure with {len(fig.data)} traces")
            return fig

        except Exception as e:
            logger.error(f"Error creating figure for {symbol}: {e}")
            return self.create_initial_figure(symbol)

    async def connect_dxlink(self) -> None:
        try:
            config = RedisConfigManager()
            credentials = Credentials(config=config, env="Live")
            self.dxlink = DXLinkManager()
            await self.dxlink.open(credentials)
            logger.info("Connected to DXLink")

        except Exception as e:
            logger.error(f"Error connecting to DXLink: {e}")

    def run_server(self, debug: bool = True, port: int = 8050) -> None:
        def run_async_loop() -> None:
            logger.debug("Starting async loop")
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            try:
                self.loop.run_until_complete(self.connect_dxlink())
                logger.debug("DXLink connection established")

                # Start subscription queue processor
                logger.debug("Starting subscription queue processor thread")
                subscription_thread = Thread(
                    target=self.process_subscription_queue, daemon=True
                )
                subscription_thread.start()

                self.loop.run_forever()
            except Exception as e:
                logger.error(f"Error in async loop: {e}", exc_info=True)

        logger.info("Starting server...")
        async_thread = Thread(target=run_async_loop, daemon=True)
        async_thread.start()
        logger.info("Starting Dash server...")
        self.app.run_server(debug=debug, port=port)
