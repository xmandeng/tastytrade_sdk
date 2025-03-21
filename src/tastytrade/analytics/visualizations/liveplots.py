import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import dash
import pandas as pd
import plotly.graph_objects as go
import plotly.subplots
import polars as pl
from dash import Input, Output, State, dcc, html
from dash.dependencies import ALL
from dash.exceptions import PreventUpdate

from tastytrade.analytics.indicators.momentum import hull, macd
from tastytrade.analytics.visualizations.plots import HorizontalLine, VerticalLine
from tastytrade.messaging.models.events import BaseEvent, CandleEvent
from tastytrade.providers.market import MarketDataProvider
from tastytrade.utils.helpers import parse_candle_symbol

logger = logging.getLogger(__name__)


# Extend MarketDataProvider with callback support
class EventDrivenMarketDataProvider(MarketDataProvider):
    """Extension of MarketDataProvider with event callback support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_callbacks = {}

    def register_update_callback(self, event_symbol: str, callback):
        """Register a callback to be triggered when data for a symbol is updated."""
        if event_symbol not in self.update_callbacks:
            self.update_callbacks[event_symbol] = []
        self.update_callbacks[event_symbol].append(callback)
        logger.debug(f"Registered update callback for {event_symbol}")
        return callback  # Return the callback for convenience

    def unregister_update_callback(self, event_symbol: str, callback):
        """Remove a registered callback."""
        if (
            event_symbol in self.update_callbacks
            and callback in self.update_callbacks[event_symbol]
        ):
            self.update_callbacks[event_symbol].remove(callback)
            logger.debug(f"Unregistered update callback for {event_symbol}")

    def handle_update(self, event: BaseEvent) -> None:
        """Handle incoming market data events and trigger callbacks."""
        event_key = f"{event.__class__.__name__}:{event.eventSymbol}"

        # Call the original handle_update method
        super().handle_update(event)

        # Trigger callbacks if registered for this symbol
        if event_key in self.update_callbacks and self.update_callbacks[event_key]:
            for callback in self.update_callbacks[event_key]:
                try:
                    callback(event_key, event)
                except Exception as e:
                    logger.error(f"Error in update callback for {event_key}: {e}")


class LiveMarketChart:
    """Event-driven live updating market data chart with technical indicators."""

    def __init__(
        self,
        streamer: MarketDataProvider,
        symbol: str,
        interval: str = "5m",
        lookback_days: int = 1,
        chart_tz: str = "America/New_York",
        horizontal_lines: Optional[List[HorizontalLine]] = None,
        vertical_lines: Optional[List[VerticalLine]] = None,
        height: int = 800,
        use_hull: bool = True,
        use_macd: bool = True,
        id: Optional[str] = None,
    ):
        """Initialize the live market chart.

        Args:
            streamer: MarketDataProvider instance
            symbol: Symbol to chart (e.g., "SPX")
            interval: Time interval (e.g., "m", "5m", "1h")
            lookback_days: Number of days of historical data to display
            chart_tz: Timezone for the chart (e.g., "America/New_York")
            horizontal_lines: Optional list of HorizontalLine objects
            vertical_lines: Optional list of VerticalLine objects
            height: Height of the chart in pixels
            use_hull: Whether to display Hull MA
            use_macd: Whether to display MACD
            id: Optional ID for the chart component
        """
        self.streamer = streamer
        self.symbol = symbol
        self.interval = interval
        self.lookback_days = lookback_days
        self.chart_tz = chart_tz
        self.horizontal_lines = horizontal_lines or []
        self.vertical_lines = vertical_lines or []
        self.height = height
        self.use_hull = use_hull
        self.use_macd = use_macd

        # Format the event symbol for candles with the correct structure
        self.event_symbol = f"{symbol}{{={interval}}}"

        # Generate a unique ID if not provided
        self.id = id or f"chart-{symbol}-{interval}-{datetime.now().strftime('%H%M%S')}"

        # Ensure we have both the ticker symbol and the formatted event symbol
        self.ticker_symbol, _ = parse_candle_symbol(self.event_symbol)
        if self.ticker_symbol is None:
            self.ticker_symbol = symbol

        # Initialize storage for update status
        self.update_callback = None
        self.last_update_time: Optional[datetime] = None
        self.is_initialized = False

    async def initialize(self):
        """Initialize the chart and register for updates."""
        if self.is_initialized:
            return

        # Initialize prior day data if needed for reference lines
        await self.get_prior_day_data()

        # Register for updates if we have an EventDrivenMarketDataProvider
        if hasattr(self.streamer, "register_update_callback"):
            # Register a callback for updates
            self.update_callback = self.streamer.register_update_callback(
                self.event_symbol, self._on_data_update
            )
            logger.info(f"Registered update callback for {self.event_symbol}")
        else:
            logger.warning(
                "Streamer does not support event callbacks, falling back to interval updates"
            )

        self.is_initialized = True

    async def cleanup(self):
        """Unregister callbacks and clean up resources."""
        if hasattr(self.streamer, "unregister_update_callback") and self.update_callback:
            self.streamer.unregister_update_callback(self.event_symbol, self.update_callback)
            logger.info(f"Unregistered update callback for {self.event_symbol}")

    def _on_data_update(self, event_key: str, event: BaseEvent):
        """Handle data update events from the MarketDataProvider."""
        try:
            # Store the update time
            self.last_update_time = datetime.now()

            # Get the current app context
            app = dash.callback_context.app

            # Update the update-count store to trigger chart refresh
            # This uses Dash's clientside callbacks to avoid server roundtrips
            app.clientside_queue.put(
                Output(f"{self.id}-update-count", "data"),
                {
                    "timestamp": self.last_update_time.timestamp() if self.last_update_time else 0,
                    "symbol": self.event_symbol,
                    "event_type": event.__class__.__name__,
                },
            )

        except Exception as e:
            logger.error(f"Error processing update for {self.event_symbol}: {e}")

    async def get_prior_day_data(self) -> Optional[CandleEvent]:
        """Get the prior day's OHLC data for reference lines."""
        try:
            # Try to get daily candle data for the symbol
            daily_symbol = f"{self.ticker_symbol}{{=d}}"

            # If we don't already have the data in the streamer, fetch it
            if (
                daily_symbol not in self.streamer.frames
                or self.streamer.frames[daily_symbol].is_empty()
            ):
                # Set the date range to get prior day data
                end_date = datetime.now()
                start_date = end_date - timedelta(days=5)  # Look back 5 days to ensure we get data

                # Fetch the daily data
                self.streamer.download(
                    symbol=daily_symbol,
                    start=start_date,
                    stop=end_date,
                    debug_mode=True,
                )

            # Get the latest daily candle (should be yesterday's close)
            if (
                daily_symbol in self.streamer.frames
                and not self.streamer.frames[daily_symbol].is_empty()
            ):
                # Sort by time descending and take the first row to get the latest daily candle
                latest_candle = (
                    self.streamer.frames[daily_symbol]
                    .sort("time", descending=True)
                    .head(1)
                    .to_pandas()
                    .iloc[0]
                )

                # Create a CandleEvent from the row data
                return CandleEvent(**latest_candle.to_dict())

            return None
        except Exception as e:
            logger.error(f"Error getting prior day data: {e}")
            return None

    def render(self) -> html.Div:
        """Render the chart component."""
        # Define the layout
        layout = html.Div(
            [
                # Chart title with symbol and interval
                html.H4(f"{self.symbol} ({self.interval} candles)", className="mb-3"),
                # Main chart container
                dcc.Graph(
                    id=f"{self.id}-graph",
                    config={
                        "displayModeBar": True,
                        "scrollZoom": True,
                        "displaylogo": False,
                    },
                    style={"height": f"{self.height}px"},
                    figure=self._create_empty_figure(),
                ),
                # Data store for tracking updates - used by event system
                dcc.Store(id=f"{self.id}-update-count", data={"timestamp": 0}),
                # Fallback interval for cases when event system isn't available
                dcc.Interval(
                    id=f"{self.id}-fallback-interval",
                    interval=1000,  # 1 second refresh
                    n_intervals=0,
                    disabled=True,  # Disabled by default, enabled if no event system
                ),
                # Hidden divs to store component properties
                html.Div(id=f"{self.id}-symbol", style={"display": "none"}, children=self.symbol),
                html.Div(
                    id=f"{self.id}-interval", style={"display": "none"}, children=self.interval
                ),
                html.Div(
                    id=f"{self.id}-event-symbol",
                    style={"display": "none"},
                    children=self.event_symbol,
                ),
                html.Div(
                    id=f"{self.id}-chart-tz", style={"display": "none"}, children=self.chart_tz
                ),
                html.Div(
                    id=f"{self.id}-lookback-days",
                    style={"display": "none"},
                    children=str(self.lookback_days),
                ),
                html.Div(
                    id=f"{self.id}-use-hull",
                    style={"display": "none"},
                    children=str(self.use_hull).lower(),
                ),
                html.Div(
                    id=f"{self.id}-use-macd",
                    style={"display": "none"},
                    children=str(self.use_macd).lower(),
                ),
            ],
            id=self.id,
            className="live-market-chart mb-4",
        )

        return layout

    def register_callbacks(self, app: dash.Dash) -> None:
        """Register all callbacks for this chart instance."""
        # Add required clientside callbacks if not already registered
        self._register_clientside_callbacks(app)

        # Main chart update callback
        @app.callback(
            Output(f"{self.id}-graph", "figure"),
            [
                Input(f"{self.id}-update-count", "data"),
                Input(f"{self.id}-fallback-interval", "n_intervals"),
            ],
            [
                State(f"{self.id}-symbol", "children"),
                State(f"{self.id}-interval", "children"),
                State(f"{self.id}-event-symbol", "children"),
                State(f"{self.id}-chart-tz", "children"),
                State(f"{self.id}-lookback-days", "children"),
                State(f"{self.id}-use-hull", "children"),
                State(f"{self.id}-use-macd", "children"),
                State(f"{self.id}-graph", "figure"),
            ],
            prevent_initial_call=True,
        )
        def update_chart(
            update_data,
            n_intervals,
            symbol,
            interval,
            event_symbol,
            chart_tz,
            lookback_days_str,
            use_hull_str,
            use_macd_str,
            current_figure,
        ):
            # Convert string parameters to proper types
            lookback_days = int(lookback_days_str)
            use_hull = use_hull_str.lower() == "true"
            use_macd = use_macd_str.lower() == "true"

            ctx = dash.callback_context
            triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None

            if not triggered_id:
                raise PreventUpdate

            # Get the dataframe for this symbol from the streamer
            df = self.streamer.frames.get(event_symbol, None)

            if df is None or df.is_empty():
                # Return an empty figure if no data is available
                return self._create_empty_figure()

            # Create a figure with the current data
            return self._create_chart_figure(
                df=df,
                symbol=symbol,
                interval=interval,
                chart_tz=chart_tz,
                lookback_days=lookback_days,
                use_hull=use_hull,
                use_macd=use_macd,
                current_figure=current_figure,
            )

    def _register_clientside_callbacks(self, app):
        """Register clientside callbacks for event handling if not already registered."""
        # Check if our clientside function already exists
        clientside_functions = getattr(app, "_livechart_clientside_registered", set())

        if "update_trigger" not in clientside_functions:
            app._livechart_clientside_registered = clientside_functions.union({"update_trigger"})

            # Add clientside JavaScript
            app.clientside_callback(
                """
                function(n_clicks) {
                    if (!window.livechart_update_counts) {
                        window.livechart_update_counts = {};
                    }
                    return n_clicks + 1;
                }
                """,
                Output({"type": "livechart-update-trigger", "id": ALL}, "data"),
                [Input({"type": "livechart-update-button", "id": ALL}, "n_clicks")],
                prevent_initial_call=True,
            )

    def _create_empty_figure(self) -> go.Figure:
        """Create an empty figure with a loading message."""
        fig = go.Figure()

        fig.update_layout(
            template="plotly_dark",
            title=dict(text=f"{self.symbol} ({self.interval}) Loading...", x=0.5, y=0.95),
            annotations=[
                dict(
                    text="Loading market data...",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=20, color="white"),
                )
            ],
            plot_bgcolor="rgb(25,25,25)",
            paper_bgcolor="rgb(25,25,25)",
            xaxis_rangeslider_visible=False,
            showlegend=False,
            height=self.height,
        )

        return fig

    def _create_chart_figure(
        self,
        df: pl.DataFrame,
        symbol: str,
        interval: str,
        chart_tz: str,
        lookback_days: int,
        use_hull: bool,
        use_macd: bool,
        current_figure: Optional[Dict] = None,
    ) -> go.Figure:
        """Create a figure with candlesticks, MACD, and Hull MA."""
        try:
            # Convert to pandas for compatibility with existing functions
            pdf = df.to_pandas()

            # Filter by time to limit the lookback period
            cutoff_time = datetime.now() - timedelta(days=lookback_days)
            pdf = pdf[pdf["time"] >= cutoff_time]

            if pdf.empty:
                return self._create_empty_figure()

            # Sort by time to ensure correct ordering
            pdf = pdf.sort_values("time")

            # Calculate MACD if requested
            if use_macd:
                # Use the first close price as the prior close for MACD calculation
                prior_close = pdf["close"].iloc[0]
                df_macd = macd(
                    df, prior_close=prior_close, fast_length=12, slow_length=26, macd_length=9
                )
                pdf_macd = df_macd.to_pandas()
            else:
                pdf_macd = pdf.copy()

            # Calculate Hull MA if requested
            hma_df = pd.DataFrame()
            if use_hull:
                try:
                    # Use the first close price as pad_value for Hull calculation
                    pad_value = pdf["close"].iloc[0]
                    hma_df = hull(df, pad_value=pad_value)
                except Exception as e:
                    logger.error(f"Error calculating Hull MA: {e}")

            # Create the subplots based on whether MACD is used
            fig = plotly.subplots.make_subplots(
                rows=2 if use_macd else 1,
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.7, 0.3] if use_macd else [1],
            )

            # Add candlestick chart
            fig.add_trace(
                go.Candlestick(
                    x=pdf["time"],
                    open=pdf["open"],
                    high=pdf["high"],
                    low=pdf["low"],
                    close=pdf["close"],
                    name="Price",
                    showlegend=False,
                    increasing_line_color="#4CAF50",  # Green outline for up candles
                    decreasing_line_color="#EF5350",  # Red outline for down candles
                    increasing_fillcolor="rgba(19, 19, 19, 0.1)",  # Semi-transparent fill for up candles
                    decreasing_fillcolor="#EF5350",  # Red fill for down candles
                    line_width=0.75,
                ),
                row=1,
                col=1,
            )

            # Add Hull MA if available
            if not hma_df.empty and use_hull:
                for i in range(1, len(hma_df)):
                    fig.add_trace(
                        go.Scatter(
                            x=hma_df["time"].iloc[i - 1 : i + 1],
                            y=hma_df["HMA"].iloc[i - 1 : i + 1],
                            mode="lines",
                            line=dict(
                                color=(
                                    "#01FFFF" if hma_df["HMA_color"].iloc[i] == "Up" else "#FF66FE"
                                ),
                                width=0.6,
                            ),
                            showlegend=False,
                            name="HMA",
                        ),
                        row=1,
                        col=1,
                    )

            # Add MACD if requested
            if use_macd:
                # MACD line
                fig.add_trace(
                    go.Scatter(
                        x=pdf_macd["time"],
                        y=pdf_macd["Value"],
                        mode="lines",
                        name="MACD",
                        line=dict(color="#01FFFF", width=1),
                        showlegend=False,
                    ),
                    row=2,
                    col=1,
                )

                # Signal line
                fig.add_trace(
                    go.Scatter(
                        x=pdf_macd["time"],
                        y=pdf_macd["avg"],
                        mode="lines",
                        name="Signal",
                        line=dict(color="#F8E9A6", width=1),
                        showlegend=False,
                    ),
                    row=2,
                    col=1,
                )

                # Histogram
                fig.add_trace(
                    go.Bar(
                        x=pdf_macd["time"],
                        y=pdf_macd["diff"],
                        name="Histogram",
                        marker_color=pdf_macd["diff_color"],
                        showlegend=False,
                    ),
                    row=2,
                    col=1,
                )

                # Zero line for MACD
                fig.add_shape(
                    type="line",
                    x0=pdf_macd["time"].min(),
                    x1=pdf_macd["time"].max(),
                    y0=0,
                    y1=0,
                    line=dict(color="gray", width=1, dash="dot"),
                    row=2,
                    col=1,
                )

            # Add horizontal lines
            for h_line in self.horizontal_lines:
                # Calculate x-axis range based on line properties
                if h_line.extend_to_end:
                    x0 = pdf["time"].min()
                    x1 = pdf["time"].max()
                else:
                    x0 = h_line.start_time if h_line.start_time else pdf["time"].min()
                    x1 = h_line.end_time if h_line.end_time else pdf["time"].max()

                # Add the line
                fig.add_shape(
                    type="line",
                    x0=x0,
                    x1=x1,
                    y0=h_line.price,
                    y1=h_line.price,
                    line=dict(
                        color=h_line.color,
                        width=h_line.line_width,
                        dash=h_line.line_dash,
                    ),
                    opacity=h_line.opacity,
                    row=1,
                    col=1,
                )

                # Add label if specified
                if h_line.show_label and h_line.label is not None:
                    if h_line.text_position == "left":
                        x_pos = x0
                    elif h_line.text_position == "right":
                        x_pos = x1
                    else:  # middle
                        x_pos = x0 + (x1 - x0) / 2

                    fig.add_annotation(
                        x=x_pos,
                        y=h_line.price,
                        text=h_line.label,
                        showarrow=False,
                        font=dict(color=h_line.color, size=h_line.label_font_size),
                        bgcolor="rgba(25,25,25,0.7)",
                        bordercolor=h_line.color,
                        borderwidth=1,
                        borderpad=4,
                        xanchor=(
                            "left"
                            if h_line.text_position == "left"
                            else "right" if h_line.text_position == "right" else "center"
                        ),
                        yanchor="bottom",
                        row=1,
                        col=1,
                    )

            # Add vertical lines
            for v_line in self.vertical_lines:
                # Convert to timezone if needed
                line_time = v_line.time

                # Add the vertical line to appropriate panels
                y_min, y_max = pdf["low"].min(), pdf["high"].max()
                y_range = y_max - y_min
                y_min -= 0.05 * y_range  # Add 5% padding
                y_max += 0.05 * y_range

                fig.add_shape(
                    type="line",
                    x0=line_time,
                    x1=line_time,
                    y0=y_min,
                    y1=y_max,
                    line=dict(
                        color=v_line.color,
                        width=v_line.line_width,
                        dash=v_line.line_dash,
                    ),
                    opacity=v_line.opacity,
                    row=1,
                    col=1,
                )

                # Add MACD panel line if using MACD and set to span subplots
                if use_macd and v_line.span_subplots:
                    macd_min = (
                        min(pdf_macd["diff"].min(), pdf_macd["Value"].min(), pdf_macd["avg"].min())
                        * 1.2
                    )
                    macd_max = (
                        max(pdf_macd["diff"].max(), pdf_macd["Value"].max(), pdf_macd["avg"].max())
                        * 1.2
                    )

                    fig.add_shape(
                        type="line",
                        x0=line_time,
                        x1=line_time,
                        y0=macd_min,
                        y1=macd_max,
                        line=dict(
                            color=v_line.color,
                            width=v_line.line_width,
                            dash=v_line.line_dash,
                        ),
                        opacity=v_line.opacity,
                        row=2,
                        col=1,
                    )

                # Add label if specified
                if v_line.show_label and v_line.label is not None:
                    if v_line.text_position == "top":
                        y_pos = y_max
                        y_anchor = "bottom"
                    elif v_line.text_position == "bottom":
                        y_pos = y_min
                        y_anchor = "top"
                    else:  # middle
                        y_pos = (y_min + y_max) / 2
                        y_anchor = "middle"

                    text_angle = 270 if v_line.text_orientation == "vertical" else 0

                    fig.add_annotation(
                        x=line_time,
                        y=y_pos,
                        text=v_line.label,
                        showarrow=False,
                        font=dict(color=v_line.color, size=v_line.label_font_size),
                        bgcolor=f"rgba(25,25,25,{v_line.label_bg_opacity})",
                        bordercolor=v_line.color,
                        borderwidth=1,
                        borderpad=v_line.label_padding,
                        textangle=text_angle,
                        xanchor="center",
                        yanchor=y_anchor,
                        align="center",
                        row=1,
                        col=1,
                    )

            # Update layout
            fig.update_layout(
                template="plotly_dark",
                xaxis_rangeslider_visible=False,
                plot_bgcolor="rgb(25,25,25)",
                paper_bgcolor="rgb(25,25,25)",
                margin=dict(l=30, r=5, t=50, b=10),
                height=self.height,
                showlegend=False,
                uirevision="true",  # Preserve zoom level on updates
            )

            # Set y-axis styling for price chart
            fig.update_yaxes(
                gridcolor="rgba(128,128,128,0.1)",
                zerolinecolor="rgba(128,128,128,0.1)",
                ticklabelposition="outside",
                automargin=True,
                ticklen=4,
                tickwidth=1,
                ticks="outside",
                ticksuffix=" ",
                tickfont=dict(size=11),
                showgrid=True,
                zeroline=False,
                showticklabels=True,
                dtick=10,
                minor=dict(
                    ticklen=2,
                    tickwidth=1,
                    tickcolor="rgba(150,150,150,0.5)",
                    tickmode="linear",
                    dtick=5,
                    showgrid=False,
                    ticks="outside",
                ),
                row=1,
                col=1,
            )

            # Set MACD y-axis styling if used
            if use_macd:
                fig.update_yaxes(
                    gridcolor="rgba(128,128,128,0.1)",
                    zerolinecolor="rgba(128,128,128,0.1)",
                    side="left",
                    ticklabelposition="outside",
                    automargin=True,
                    ticklen=4,
                    tickwidth=1,
                    ticks="outside",
                    ticksuffix=" ",
                    tickfont=dict(size=11),
                    showgrid=True,
                    zeroline=False,
                    showticklabels=True,
                    row=2,
                    col=1,
                )

            # Set x-axis styling
            fig.update_xaxes(
                gridcolor="rgba(128,128,128,0.1)",
                zerolinecolor="rgba(128,128,128,0.1)",
                automargin=True,
                dtick=30 * 60 * 1000,  # 30 minutes in milliseconds
            )

            # Preserve the current view if the figure exists
            if current_figure and "layout" in current_figure:
                if (
                    "xaxis" in current_figure["layout"]
                    and "range" in current_figure["layout"]["xaxis"]
                ):
                    fig.layout.xaxis.range = current_figure["layout"]["xaxis"]["range"]
                if (
                    "yaxis" in current_figure["layout"]
                    and "range" in current_figure["layout"]["yaxis"]
                ):
                    fig.layout.yaxis.range = current_figure["layout"]["yaxis"]["range"]

            return fig

        except Exception as e:
            logger.error(f"Error creating chart figure: {e}")
            return self._create_empty_figure()


class LiveChartDashboard:
    """Dashboard container for multiple LiveMarketChart components."""

    def __init__(self, app: dash.Dash):
        """Initialize the dashboard.

        Args:
            app: Dash application instance
        """
        self.app = app
        self.charts: List[LiveMarketChart] = []

    def add_chart(self, chart: LiveMarketChart) -> None:
        """Add a chart to the dashboard and register its callbacks.

        Args:
            chart: LiveMarketChart instance to add
        """
        self.charts.append(chart)
        chart.register_callbacks(self.app)

    def render(self) -> html.Div:
        """Render the complete dashboard with all charts.

        Returns:
            A Dash component representing the dashboard
        """
        return html.Div(
            [
                html.H2("Market Data Dashboard", className="mb-4"),
                html.Div([chart.render() for chart in self.charts], className="chart-container"),
            ],
            className="dashboard",
        )

    async def initialize(self) -> None:
        """Initialize all charts in the dashboard."""
        for chart in self.charts:
            await chart.initialize()

    async def cleanup(self) -> None:
        """Clean up all charts when dashboard is closed."""
        for chart in self.charts:
            await chart.cleanup()


# Example usage in a Dash application
"""
import asyncio
import dash
import dash_bootstrap_components as dbc
import influxdb_client
from dash import Dash, html

from tastytrade.analytics.visualizations.plots import HorizontalLine, VerticalLine
from tastytrade.config import RedisConfigManager
from tastytrade.connections import InfluxCredentials
from tastytrade.providers.subscriptions import RedisSubscription

# Define an async function to set up and run the application
async def run_app():
    # Initialize the Dash app
    app = Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])

    # Set up Redis and InfluxDB connections
    config = RedisConfigManager()
    subscription = RedisSubscription(config=config)
    await subscription.connect()

    influx_user = InfluxCredentials(config=config)
    influxdb = influxdb_client.InfluxDBClient(
        url=influx_user.url, token=influx_user.token, org=influx_user.org
    )

    # Create an event-driven market data provider
    streamer = EventDrivenMarketDataProvider(subscription, influxdb)

    # Create a dashboard container
    dashboard = LiveChartDashboard(app)

    # Add SPX 1-minute chart with prior day levels and opening ranges
    spx_chart = LiveMarketChart(
        streamer=streamer,
        symbol="SPX",
        interval="m",
        lookback_days=1,
        height=600,
        use_hull=True,
        use_macd=True,
    )

    # Add AAPL 5-minute chart
    aapl_chart = LiveMarketChart(
        streamer=streamer,
        symbol="AAPL",
        interval="5m",
        lookback_days=1,
        height=600,
    )

    # Add charts to dashboard
    dashboard.add_chart(spx_chart)
    dashboard.add_chart(aapl_chart)

    # Set the app layout
    app.layout = dashboard.render()

    # Initialize all charts
    await dashboard.initialize()

    # Subscribe to market data for the charts
    await streamer.subscribe("CandleEvent", "SPX{=*}")
    await streamer.subscribe("CandleEvent", "AAPL{=*}")

    # Add a callback to clean up on server shutdown
    @app.server.before_first_request
    def _setup():
        @app.server.teardown_appcontext
        async def shutdown_cleanup(exception=None):
            await dashboard.cleanup()

    # Return the app object
    return app

# Run the application
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(run_app())
    app.run_server(debug=True, port=8888)
"""


# Another example: Adding horizontal lines based on prior day data
"""
import asyncio
from datetime import datetime, timedelta

async def add_prior_day_levels(chart):
    # Get prior day's OHLC
    prior_day = await chart.get_prior_day_data()

    if prior_day:
        # Create horizontal lines based on prior day data
        chart.horizontal_lines = [
            HorizontalLine(
                price=prior_day.close,
                label="Prior Close",
                color="#FF66FE",
                line_dash="dot",
                opacity=0.45,
            ),
            HorizontalLine(
                price=prior_day.high,
                label="Prior High",
                color="#4CAF50",
                line_dash="dot",
                opacity=0.45,
            ),
            HorizontalLine(
                price=prior_day.low,
                label="Prior Low",
                color="#F44336",
                line_dash="dot",
                opacity=0.45,
            ),
        ]
"""


# Example: Using the chart in a Flask application with Dash
"""
from flask import Flask
import dash
from dash import Dash
import dash_bootstrap_components as dbc
import asyncio

# Create Flask app
server = Flask(__name__)

# Create Dash app with Flask server
app = Dash(
    __name__,
    server=server,
    url_base_pathname='/dash/',
    external_stylesheets=[dbc.themes.DARKLY]
)

# Dashboard setup code
dashboard = LiveChartDashboard(app)

# Route for the main Flask application
@server.route('/')
def index():
    return 'Flask Application with Dash charts at <a href="/dash/">Dashboard</a>'

# Function to initialize charts asynchronously
async def initialize_charts():
    # Setup code...
    await dashboard.initialize()

# Initialize on startup using Flask context
with server.app_context():
    asyncio.run(initialize_charts())

# Run the Flask application
if __name__ == '__main__':
    server.run(debug=True, port=8888)
"""
