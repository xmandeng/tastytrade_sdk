import asyncio
import logging

import dash_bootstrap_components as dbc
import influxdb_client
from dash import Dash, html

from tastytrade.analytics.visualizations.liveplots import LiveMarketChart
from tastytrade.common.logging import setup_logging
from tastytrade.config import RedisConfigManager
from tastytrade.connections import InfluxCredentials
from tastytrade.providers.market import EventDrivenProvider
from tastytrade.providers.subscriptions import RedisSubscription

logging.getLogger().handlers.clear()

setup_logging(
    level=logging.INFO,
    console=True,
)


# Define an async function for our application setup
async def main():
    # Create the Dash application
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
    streamer = EventDrivenProvider(subscription, influxdb)

    # Create a chart instance
    chart = LiveMarketChart(
        streamer=streamer,
        symbol="BTC/USD:CXTALP",
        interval="5m",
        lookback_days=1,
        use_hull=True,
        use_macd=True,
    )

    # Set up the app layout
    app.layout = html.Div([html.H1("Live Market Data"), chart.render()])

    # Register callbacks with your Dash app
    chart.register_callbacks(app)

    # Initialize the chart (this registers for events)
    await chart.initialize()

    # Subscribe to market data
    await streamer.subscribe("CandleEvent", "BTC/USD:CXTALP{=5m}")

    # Return the app for running the server
    return app


# Entry point for the application
if __name__ == "__main__":
    # Get the event loop
    loop = asyncio.get_event_loop()

    # Run the async setup
    app = loop.run_until_complete(main())

    # Start the Dash server
    app.run_server(debug=True, port=8050)
