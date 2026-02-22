"""Backtest CLI — entry points for the backtesting framework.

Orchestrates the three backtest components:
    replay   — Read historical candles from InfluxDB, publish to Redis
    run      — Subscribe to Redis, process through engine, publish signals
    persist  — Subscribe to backtest signals on Redis, persist to InfluxDB
    backtest — Orchestrated mode: runs all three as concurrent async tasks

Usage:
    tasty-backtest backtest --symbol SPX --start 2025-01-01 --end 2025-02-01
    tasty-backtest backtest --symbol NVDA --start 2025-06-01 --end 2025-07-01 \\
        --signal-interval 5m --pricing-interval 1m
"""

import asyncio
import logging
import os
from datetime import datetime

import click
from influxdb_client import InfluxDBClient

from tastytrade.analytics.engines.hull_macd import HullMacdEngine
from tastytrade.backtest.models import BacktestConfig, BacktestSignal
from tastytrade.backtest.publisher import BacktestPublisher
from tastytrade.backtest.replay import BacktestReplay
from tastytrade.backtest.runner import BacktestRunner
from tastytrade.common.logging import setup_logging
from tastytrade.config.manager import RedisConfigManager
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor
from tastytrade.providers.market import MarketDataProvider
from tastytrade.providers.subscriptions import RedisPublisher, RedisSubscription
from tastytrade.signal.runner import EngineRunner

logger = logging.getLogger(__name__)


async def run_backtest_orchestrated(config: BacktestConfig) -> None:
    """Run a complete backtest — replay, engine, and persistence.

    Orchestrates all three components as concurrent async tasks
    within a single process, communicating through Redis.
    """
    redis_config = RedisConfigManager()

    # --- Replay setup (InfluxDB → Redis) ---
    influx_url = redis_config.get("INFLUX_DB_URL", "http://localhost:8086")
    influx_token = redis_config.get("INFLUX_DB_TOKEN")
    influx_org = redis_config.get("INFLUX_DB_ORG")

    if not influx_token or not influx_org:
        raise ValueError(
            "INFLUX_DB_TOKEN and INFLUX_DB_ORG are required. "
            "Ensure they are set in Redis configuration or environment."
        )

    influx_client = InfluxDBClient(url=influx_url, token=influx_token, org=influx_org)
    data_subscription = RedisSubscription(redis_config)
    provider = MarketDataProvider(
        data_feed=data_subscription,
        influx=influx_client,
    )
    replay = BacktestReplay(config=config, provider=provider)

    # --- Engine setup (Redis → Engine → Redis) ---
    engine_subscription = RedisSubscription(redis_config)
    signal_publisher = RedisPublisher()
    backtest_publisher = BacktestPublisher(
        config=config,
        inner_publisher=signal_publisher,
    )
    engine = HullMacdEngine(publisher=backtest_publisher)

    # Seed prior close for accurate indicator warmup
    prior_close = replay.seed_prior_close()
    if prior_close is not None:
        engine.set_prior_close(config.signal_symbol, prior_close)
        logger.info("Prior close seeded: %s = %.2f", config.signal_symbol, prior_close)

    runner = BacktestRunner(
        config=config,
        subscription=engine_subscription,
        engine=engine,
        publisher=backtest_publisher,
    )

    # --- Persistence setup (Redis → InfluxDB) ---
    influx_bucket = redis_config.get("INFLUX_DB_BUCKET")
    persist_subscription = RedisSubscription(redis_config)
    processor = TelegrafHTTPEventProcessor(
        url=influx_url,
        token=influx_token,
        org=influx_org,
        bucket=influx_bucket,
    )
    persist_runner = EngineRunner(
        name="backtest_signal_feed",
        subscription=persist_subscription,
        channels=["market:BacktestSignal:*"],
        event_type=BacktestSignal,
        on_event=processor.process_event,
    )

    logger.info(
        "Starting orchestrated backtest — backtest_id=%s, symbol=%s, "
        "signal=%s, pricing=%s, range=%s to %s",
        config.backtest_id,
        config.symbol,
        config.signal_interval,
        config.resolved_pricing_interval,
        config.start_date,
        config.end_date,
    )

    # --- Run all three components ---
    # 1. Setup subscriptions first (before replay publishes)
    await runner.setup()
    persist_task = asyncio.create_task(persist_runner.start())

    # Small delay to ensure subscriptions are active
    await asyncio.sleep(0.5)

    # 2. Run replay (publishes candles to Redis)
    candle_count = await asyncio.get_event_loop().run_in_executor(None, replay.run)

    # 3. Wait for signals to drain through the pipeline
    drain_seconds = 3
    logger.info(
        "Replay complete (%d candles). Draining for %ds...",
        candle_count,
        drain_seconds,
    )
    await asyncio.sleep(drain_seconds)

    # 4. Shutdown
    persist_task.cancel()
    try:
        await persist_task
    except asyncio.CancelledError:
        pass
    processor.close()
    await persist_runner.stop()
    await runner.stop()
    replay.close()
    influx_client.close()

    # --- Report results ---
    signals = runner.signals
    logger.info(
        "Backtest complete — %d signals generated from %d candles",
        len(signals),
        candle_count,
    )

    open_signals = [s for s in signals if s.signal_type == "OPEN"]
    close_signals = [s for s in signals if s.signal_type == "CLOSE"]
    bullish = [s for s in open_signals if s.direction == "BULLISH"]
    bearish = [s for s in open_signals if s.direction == "BEARISH"]

    logger.info(
        "  OPEN signals:  %d (bullish=%d, bearish=%d)",
        len(open_signals),
        len(bullish),
        len(bearish),
    )
    logger.info("  CLOSE signals: %d", len(close_signals))

    for sig in signals:
        logger.info(
            "  %s %s %s @ %s | close=%.2f entry=%s | trigger=%s",
            sig.signal_type,
            sig.direction,
            sig.eventSymbol,
            sig.start_time.strftime("%Y-%m-%d %H:%M"),
            sig.close_price,
            f"{sig.entry_price:.2f}" if sig.entry_price else "N/A",
            sig.trigger,
        )


@click.group()
def cli() -> None:
    """TastyTrade Backtesting Framework."""
    pass


@cli.command()
@click.option("--symbol", required=True, help="Market symbol (e.g., SPX, NVDA)")
@click.option(
    "--start",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date (YYYY-MM-DD)",
)
@click.option(
    "--end",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="End date (YYYY-MM-DD)",
)
@click.option(
    "--signal-interval",
    default="5m",
    help="Candle interval for signal generation (default: 5m)",
)
@click.option(
    "--pricing-interval",
    default=None,
    help="Candle interval for entry/exit pricing (auto-selected if omitted)",
)
@click.option("--log-level", default="INFO", help="Log level")
def backtest(
    symbol: str,
    start: datetime,
    end: datetime,
    signal_interval: str,
    pricing_interval: str | None,
    log_level: str,
) -> None:
    """Run a complete backtest with replay, engine, and persistence."""
    os.environ["LOG_LEVEL"] = log_level
    setup_logging(level=getattr(logging, log_level.upper()), console=True, file=False)

    config = BacktestConfig(
        symbol=symbol,
        signal_interval=signal_interval,
        pricing_interval=pricing_interval,
        start_date=start.date() if isinstance(start, datetime) else start,
        end_date=end.date() if isinstance(end, datetime) else end,
    )

    logger.info("Backtest config: %s", config.model_dump_json(indent=2))
    asyncio.run(run_backtest_orchestrated(config))


def main() -> None:
    cli()
