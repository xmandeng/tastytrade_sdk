#!/usr/bin/env python3
"""
Market Data Subscription Script

This script connects to Redis and InfluxDB, sets up a MarketDataProvider,
and subscribes to specified event types and symbols.

Usage:
    python md_subscriber.py [--event EVENT_TYPE] [--symbol SYMBOL] [--live] [--debug]
"""

import asyncio
import logging
import sys
from argparse import ArgumentParser

import influxdb_client
import pandas as pd

from tastytrade.common.logging import setup_logging
from tastytrade.config import RedisConfigManager
from tastytrade.connections import Credentials, InfluxCredentials
from tastytrade.providers.market import MarketDataProvider
from tastytrade.providers.subscriptions import RedisSubscription


def parse_args():
    parser = ArgumentParser(description="Market Data Subscription Tool")
    parser.add_argument(
        "--event",
        default="CandleEvent",
        help="Event type to subscribe to (CandleEvent, TradeEvent, etc.)",
    )
    parser.add_argument(
        "--symbol",
        default="SPX{=*}",
        help="Symbol pattern to subscribe to (e.g., SPX{=*}, NVDA, etc.)",
    )
    parser.add_argument(
        "--live", action="store_true", help="Use Live environment (default is Test)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Subscription duration in seconds (0 = indefinite)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Interval in seconds between showing latest data (0 = don't show data)",
    )
    return parser.parse_args()


async def display_data_periodically(streamer, event_type, symbol, interval):
    """Display the latest data periodically."""
    try:
        # Construct the key based on event type and symbol
        key = f"{event_type}:{symbol}"

        while True:
            if key in streamer.frames and not streamer[key].is_empty():
                print("\n--- Latest Data ---")
                print(f"Source: {key}")
                print(f"Total rows: {streamer[key].shape[0]}")
                print(f"Last update: {streamer.updates.get(key, 'None')}")
                print("\nMost recent records:")

                # Show the latest 5 records
                latest = streamer[key].sort("time", descending=True).head(5)

                # Convert to pandas for display
                pd.set_option("display.max_columns", None)
                pd.set_option("display.width", None)

                print(latest.to_pandas())
                print("-" * 40)
            else:
                print(f"No data available yet for {key}")

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        print("Data display stopped")


async def main():
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level=log_level, console=True, file=True)
    logger = logging.getLogger(__name__)

    # Determine environment
    env = "Live" if args.live else "Test"

    # Initialize Redis configuration
    logger.info("Initializing configuration...")
    config = RedisConfigManager()
    config.initialize()

    # Set up credentials
    logger.info(f"Setting up credentials for {env} environment")
    credentials = Credentials(config=config, env=env)

    # Set up InfluxDB connection
    logger.info("Connecting to InfluxDB...")
    influx_user = InfluxCredentials(config=config)
    influxdb = influxdb_client.InfluxDBClient(
        url=influx_user.url, token=influx_user.token, org=influx_user.org
    )

    display_task: asyncio.Task | None = None  # type: ignore[type-arg]
    subscription: RedisSubscription | None = None
    streamer: MarketDataProvider | None = None

    try:
        # Set up Redis subscription and market data provider
        logger.info("Setting up Redis subscription...")
        subscription = RedisSubscription(config=config)
        await subscription.connect()

        logger.info("Creating market data provider...")
        streamer = MarketDataProvider(subscription, influxdb)

        # Subscribe to specified event and symbol
        logger.info(f"Subscribing to {args.event} for {args.symbol}")
        await streamer.subscribe(args.event, args.symbol)
        logger.info(f"Successfully subscribed to {args.event} for {args.symbol}")

        # Set up data display task if interval > 0
        if args.interval > 0:
            logger.info(
                f"Setting up data display to refresh every {args.interval} seconds"
            )
            display_task = asyncio.create_task(
                display_data_periodically(
                    streamer, args.event, args.symbol, args.interval
                )
            )

        # Keep the subscription active
        if args.duration > 0:
            logger.info(f"Running for {args.duration} seconds")
            await asyncio.sleep(args.duration)
        else:
            logger.info("Running indefinitely (press Ctrl+C to stop)")
            # This will run until interrupted
            while True:
                await asyncio.sleep(3600)  # Sleep for an hour at a time

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1
    finally:
        # Clean up
        if display_task is not None:
            display_task.cancel()
            try:
                await display_task
            except asyncio.CancelledError:
                pass

        if subscription is not None:
            try:
                logger.info(f"Unsubscribing from {args.event} for {args.symbol}")
                if streamer is not None:
                    await streamer.unsubscribe(args.event, args.symbol)
                logger.info("Closing Redis subscription...")
                await subscription.close()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

        if "influxdb" in locals():
            logger.info("Closing InfluxDB connection...")
            influxdb.close()

        logger.info("Cleanup complete")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""
# Basic usage (subscribes to all SPX candles in Test environment)
python -m tastytrade.scripts.md_subscriber

# Subscribe to NVDA trade events in Live environment
python -m tastytrade.scripts.md_subscriber --event TradeEvent --symbol NVDA --live

# Subscribe and display data every 5 seconds
python -m tastytrade.scripts.md_subscriber --symbol "SPY{=5m}" --interval 5

# Run for 2 minutes then exit
python -m tastytrade.scripts.md_subscriber --duration 120

# Debug mode with data display
python -m tastytrade.scripts.md_subscriber --debug
"""
