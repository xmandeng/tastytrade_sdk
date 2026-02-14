"""
Standalone signal detection service.

Subscribes to candle events from Redis, runs signal detection,
and publishes trade signals back to Redis.

Usage: tasty-signal run --symbols SPX --intervals 5m
"""

import asyncio
import logging
import os

import click

from tastytrade.analytics.engines.hull_macd import HullMacdEngine
from tastytrade.common.logging import setup_logging
from tastytrade.common.observability import init_observability
from tastytrade.config.manager import RedisConfigManager
from tastytrade.messaging.models.events import CandleEvent
from tastytrade.providers import RedisPublisher
from tastytrade.providers.subscriptions import RedisSubscription

logger = logging.getLogger(__name__)


async def run_signal_service(symbols: list[str], intervals: list[str]) -> None:
    """Run the signal detection service."""
    config = RedisConfigManager()

    # Set up Redis subscription for candle events
    subscription = RedisSubscription(config)
    await subscription.connect()

    # Set up signal engine and Redis publisher
    publisher = RedisPublisher()
    engine = HullMacdEngine()
    engine.on_signal = publisher.publish

    # Subscribe to candle channels for each symbol/interval
    for symbol in symbols:
        for interval in intervals:
            pattern = f"market:CandleEvent:{symbol}{{={interval}}}"
            await subscription.subscribe(pattern, event_type=CandleEvent)
            logger.info("Listening for candles on %s", pattern)

    logger.info("Signal service started — %d engine(s) active", 1)

    try:
        # Process candle events from the queue
        while True:
            for _key, queue in subscription.queue.items():
                if not queue.empty():
                    event = queue.get_nowait()
                    engine.on_candle_event(event)
            await asyncio.sleep(0.01)
    except asyncio.CancelledError:
        logger.info("Signal service shutting down")
    finally:
        publisher.close()
        await subscription.close()


@click.group()
def cli():
    """TastyTrade Signal Detection Service."""
    pass


@cli.command()
@click.option(
    "--symbols", required=True, help="Comma-separated symbols (e.g., SPX,SPY)"
)
@click.option(
    "--intervals", default="5m", help="Comma-separated intervals (e.g., 5m,15m)"
)
@click.option("--log-level", default="INFO", help="Log level")
def run(symbols: str, intervals: str, log_level: str):
    """Run the signal detection service."""
    os.environ["LOG_LEVEL"] = log_level
    if os.getenv("GRAFANA_CLOUD_TOKEN"):
        init_observability()
        logger.info("Grafana Cloud logging enabled")
    else:
        setup_logging(
            level=getattr(logging, log_level.upper()), console=True, file=False
        )

    symbol_list = [s.strip() for s in symbols.split(",")]
    interval_list = [i.strip() for i in intervals.split(",")]
    asyncio.run(run_signal_service(symbol_list, interval_list))


def main():
    cli()
