"""Signal CLI — factory for EngineRunner instances.

Decides what to run: picks the engine/processor, channels, and event type.
Constructs an EngineRunner with the specific config and starts it.

Commands:
    run      — Signal detection (Redis → HullMacdEngine → Redis)
    persist  — TradeSignalFeed (Redis → TelegrafHTTPEventProcessor → InfluxDB)

Usage:
    tasty-signal run --symbols SPX --intervals 5m
    tasty-signal persist --channels "market:TradeSignal:*"
"""

import asyncio
import logging
import os

import click

from tastytrade.analytics.engines.hull_macd import HullMacdEngine
from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.common.logging import setup_logging
from tastytrade.common.observability import init_observability
from tastytrade.config.manager import RedisConfigManager
from tastytrade.messaging.models.events import CandleEvent
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor
from tastytrade.providers.subscriptions import RedisPublisher, RedisSubscription
from tastytrade.signal.runner import EngineRunner

logger = logging.getLogger(__name__)


async def run_signal_service(symbols: list[str], intervals: list[str]) -> None:
    """Construct and start a HullMacd EngineRunner."""
    config = RedisConfigManager()
    subscription = RedisSubscription(config)
    publisher = RedisPublisher()
    engine = HullMacdEngine(publisher=publisher)

    channels = [
        f"market:CandleEvent:{symbol}{{={interval}}}"
        for symbol in symbols
        for interval in intervals
    ]

    runner = EngineRunner(
        name=engine.name,
        subscription=subscription,
        channels=channels,
        event_type=CandleEvent,
        on_event=engine.on_candle_event,
        publisher=publisher,
    )

    try:
        await runner.start()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.stop()


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


async def run_trade_signal_feed(channels: list[str]) -> None:
    """Construct and start a TradeSignalFeed EngineRunner (InfluxDB sink)."""
    config = RedisConfigManager()
    subscription = RedisSubscription(config)
    processor = TelegrafHTTPEventProcessor()

    runner = EngineRunner(
        name="trade_signal_feed",
        subscription=subscription,
        channels=channels,
        event_type=TradeSignal,
        on_event=processor.process_event,
    )

    try:
        await runner.start()
    except asyncio.CancelledError:
        pass
    finally:
        processor.close()
        await runner.stop()


@cli.command()
@click.option(
    "--channels",
    default="market:TradeSignal:*",
    help="Comma-separated Redis channel patterns",
)
@click.option("--log-level", default="INFO", help="Log level")
def persist(channels: str, log_level: str) -> None:
    """Persist signals from Redis to InfluxDB."""
    os.environ["LOG_LEVEL"] = log_level
    if os.getenv("GRAFANA_CLOUD_TOKEN"):
        init_observability()
        logger.info("Grafana Cloud logging enabled")
    else:
        setup_logging(
            level=getattr(logging, log_level.upper()), console=True, file=False
        )

    channel_list = [c.strip() for c in channels.split(",")]
    asyncio.run(run_trade_signal_feed(channel_list))


def main():
    cli()
