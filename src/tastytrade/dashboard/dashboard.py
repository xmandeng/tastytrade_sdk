# src/tastytrade/dashboard/dashboard.py
from __future__ import annotations

import asyncio
import logging
from threading import Thread
from typing import Dict, List, Optional, cast

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Dash, dcc, html
from dash.dependencies import MATCH, Input, Output, State

from tastytrade.analytics.studies.averages import hull
from tastytrade.sessions import Credentials
from tastytrade.sessions.enumerations import Channels
from tastytrade.sessions.sockets import DXLinkManager

from .types import Component, Figure, GraphConfig

logger = logging.getLogger(__name__)


class DashApp:
    def __init__(self) -> None:
        self.app: Dash = Dash(
            __name__, external_stylesheets=[dbc.themes.DARKLY], title="TastyTrade Live Charts"
        )
        self.dxlink: Optional[DXLinkManager] = None
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
                                html.H1("TastyTrade Live Charts", className="text-center mb-4"),
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
                                            width=8,
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
                                            width=4,
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
                    [dbc.Col([html.Div(id="charts-container", children=[])], width=12)],
                    className="mt-4",
                ),
            ],
            fluid=True,
            className="py-4",
        )

    def setup_callbacks(self) -> None:
        @self.app.callback(
            Output("charts-container", "children"),
            Input("add-chart-button", "n_clicks"),
            State("symbol-input", "value"),
            State("charts-container", "children"),
            prevent_initial_call=True,
        )
        def add_chart(
            n_clicks: Optional[int],
            symbol: Optional[str],
            existing_charts: Optional[List[Component]],
        ) -> List[Component]:
            if not symbol:
                return existing_charts or []

            symbol = symbol.upper()

            # Check if chart already exists
            if existing_charts:
                for chart in existing_charts:
                    if chart["props"]["id"] == f"chart-card-{symbol}":
                        return existing_charts

            new_chart = self._create_chart_card(symbol)

            if existing_charts is None:
                return [new_chart]
            return existing_charts + [new_chart]

        @self.app.callback(
            Output({"type": "chart", "index": MATCH}, "figure"),
            Input({"type": "interval", "index": MATCH}, "n_intervals"),
            State({"type": "chart", "index": MATCH}, "id"),
            prevent_initial_call=True,
        )
        def update_chart(n_intervals: int, chart_id: Dict[str, str]) -> Figure:
            symbol = chart_id["index"]
            return self.update_figure(symbol)

        @self.app.callback(
            Output("charts-container", "children", allow_duplicate=True),
            Input({"type": "close-chart", "index": MATCH}, "n_clicks"),
            State({"type": "close-chart", "index": MATCH}, "id"),
            State("charts-container", "children"),
            prevent_initial_call=True,
        )
        def remove_chart(
            n_clicks: Optional[int], chart_id: Dict[str, str], existing_charts: List[Component]
        ) -> List[Component]:
            if not n_clicks:
                return existing_charts

            symbol = chart_id["index"]
            return [
                chart for chart in existing_charts if chart["props"]["id"] != f"chart-card-{symbol}"
            ]

    def _create_chart_card(self, symbol: str) -> Component:
        return dbc.Card(
            [
                dbc.CardHeader(
                    [
                        dbc.Row(
                            [
                                dbc.Col(html.H4(symbol), width=10),
                                dbc.Col(
                                    dbc.Button(
                                        "×",
                                        id={"type": "close-chart", "index": symbol},
                                        className="btn-close",
                                        color="light",
                                    ),
                                    width=2,
                                    className="text-end",
                                ),
                            ]
                        )
                    ]
                ),
                dbc.CardBody(
                    [
                        dcc.Loading(
                            dcc.Graph(
                                id={"type": "chart", "index": symbol},
                                figure=self.create_initial_figure(symbol),
                                config=cast(GraphConfig, {"displayModeBar": True}),
                            ),
                            type="default",
                        ),
                        dcc.Interval(
                            id={"type": "interval", "index": symbol},
                            interval=1000,  # 1 second
                            n_intervals=0,
                        ),
                    ]
                ),
            ],
            id=f"chart-card-{symbol}",
            className="mt-3",
        )

    def create_initial_figure(self, symbol: str) -> Figure:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            showlegend=True,
            xaxis_rangeslider_visible=False,
            height=600,
            margin=dict(l=50, r=50, t=30, b=50),
            yaxis=dict(title="Price"),
            xaxis=dict(title="Time"),
            title=dict(text=f"{symbol} Loading...", x=0.5, y=0.95),
        )
        return fig

    def update_figure(self, symbol: str) -> Figure:
        if not self.dxlink:
            return self.create_initial_figure(symbol)

        try:
            df = (
                self.dxlink.router.handler[Channels.Candle]
                .processors["feed"]
                .df.loc[lambda x: x["eventSymbol"] == f"{symbol}{{=5m}}"]
            )

            if len(df) == 0:
                return self.create_initial_figure(symbol)

            # Calculate HMA
            hma_df = hull(self.dxlink, f"{symbol}{{=5m}}", length=20)

            fig = go.Figure()

            # Add candlesticks
            fig.add_trace(
                go.Candlestick(
                    x=df["time"],
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name="Price",
                )
            )

            # Add HMA
            fig.add_trace(
                go.Scatter(
                    x=hma_df["time"],
                    y=hma_df["HMA"],
                    line=dict(color="purple", width=2),
                    name="HMA-20",
                )
            )

            fig.update_layout(
                template="plotly_dark",
                showlegend=True,
                xaxis_rangeslider_visible=False,
                height=600,
                margin=dict(l=50, r=50, t=30, b=50),
                yaxis=dict(title="Price"),
                xaxis=dict(title="Time"),
            )

            return fig

        except Exception as e:
            logger.error(f"Error updating figure: {e}")
            return self.create_initial_figure(symbol)

    async def connect_dxlink(self) -> None:
        try:
            credentials = Credentials(env="Live")
            self.dxlink = DXLinkManager()
            await self.dxlink.open(credentials)
            logger.info("Connected to DXLink")

        except Exception as e:
            logger.error(f"Error connecting to DXLink: {e}")

    def run_server(self, debug: bool = True, port: int = 8050) -> None:
        # Start the asyncio event loop in a separate thread
        def run_async_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.connect_dxlink())
            loop.run_forever()

        Thread(target=run_async_loop, daemon=True).start()
        self.app.run_server(debug=debug, port=port)
