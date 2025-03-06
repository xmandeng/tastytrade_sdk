#!/usr/bin/env python3
"""
DXLink Market Data Startup Script

This script initializes DXLink connection, sets up event processors,
and subscribes to market data for specified symbols and intervals.

Usage:
    python dxlink_startup.py
"""
import asyncio
import logging
import sys
from argparse import ArgumentParser
from datetime import datetime, timedelta

from tastytrade.common.logging import setup_logging
from tastytrade.config import RedisConfigManager
from tastytrade.connections import Credentials
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.connections.subscription import RedisSubscriptionStore
from tastytrade.messaging.processors import RedisEventProcessor, TelegrafHTTPEventProcessor
from tastytrade.utils.time_series import forward_fill

# Default configuration
DEFAULT_SYMBOLS = ["BTC/USD:CXTALP", "SPX", "NVDA", "SPY", "QQQ"]
DEFAULT_INTERVALS = ["1d", "1h", "30m", "15m", "5m", "m"]
LOOKBACK_DAYS = 5


def parse_args():
    parser = ArgumentParser(description="DXLink Market Data Startup")
    parser.add_argument("--env", default="Test", choices=["Live", "Test"], help="Environment")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--fill-gaps", action="store_true", help="Fill historical data gaps")
    parser.add_argument(
        "--duration", type=int, default=0, help="Run duration in seconds (0 = indefinite)"
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level=log_level, console=True, file=True)
    logger = logging.getLogger(__name__)

    # Set up connection
    logger.info(f"Initializing DXLink in {args.env} environment")

    # Initialize Redis configuration
    config = RedisConfigManager()
    config.initialize()

    # Set API credentials
    credentials = Credentials(config=config, env=args.env)
    start_time = datetime.now() - timedelta(days=1)

    try:
        # Create and open DXLink connection
        async with DXLinkManager(
            credentials=credentials, subscription_store=RedisSubscriptionStore()
        ) as dxlink:

            # Add processors
            logger.info("Setting up event processors")
            for handler_name, event_handler in dxlink.router.handler.items():
                logger.debug(f"Adding processors to {handler_name} handler")
                event_handler.add_processor(TelegrafHTTPEventProcessor())
                event_handler.add_processor(RedisEventProcessor())

            # Subscribe to candles
            logger.info("Subscribing to candles")
            for symbol in DEFAULT_SYMBOLS:
                for interval in DEFAULT_INTERVALS:
                    logger.debug(f"Subscribing to {symbol} {interval} candles")
                    try:
                        coroutine = dxlink.subscribe_to_candles(
                            symbol=symbol,
                            interval=interval,
                            from_time=start_time,
                        )
                        await asyncio.wait_for(coroutine, timeout=10)
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout subscribing to {symbol} {interval}")
                    except Exception as e:
                        logger.error(f"Error subscribing to {symbol} {interval}: {e}")

            # Fill historical gaps if requested
            if args.fill_gaps:
                logger.info("Filling historical data gaps")
                for symbol in DEFAULT_SYMBOLS:
                    for interval in DEFAULT_INTERVALS:
                        # Use "1m" instead of "m" for forward_fill
                        interval_str = "1m" if interval == "m" else interval
                        event_symbol = f"{symbol}{{={interval_str}}}"
                        try:
                            logger.debug(f"Forward-filling {event_symbol}")
                            forward_fill(symbol=event_symbol, lookback_days=LOOKBACK_DAYS)
                        except Exception as e:
                            logger.error(f"Error forward-filling {event_symbol}: {e}")

            # Subscribe to raw symbols
            logger.info("Subscribing to symbol feeds")
            await dxlink.subscribe(DEFAULT_SYMBOLS)

            # Keep the connection alive
            if args.duration > 0:
                logger.info(f"Running for {args.duration} seconds")
                await asyncio.sleep(args.duration)
            else:
                logger.info("Running indefinitely (press Ctrl+C to stop)")
                while True:
                    await asyncio.sleep(60)
                    logger.debug("Still running...")

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
