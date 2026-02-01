"""
Market data subscription orchestrator.

This module provides the orchestration logic for market data subscriptions,
extracted from devtools/playground_testbench.ipynb for CLI integration.
"""

import asyncio
import logging
from datetime import datetime

from tastytrade.config import RedisConfigManager
from tastytrade.connections import Credentials
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.connections.subscription import RedisSubscriptionStore
from tastytrade.config.enumerations import Channels
from tastytrade.messaging.processors import (
    CandleSnapshotTracker,
    RedisEventProcessor,
    TelegrafHTTPEventProcessor,
)
from tastytrade.utils.helpers import format_candle_symbol
from tastytrade.utils.time_series import forward_fill

logger = logging.getLogger(__name__)


async def run_subscription(
    symbols: list[str],
    intervals: list[str],
    start_date: datetime,
    env_file: str = ".env",
    lookback_days: int = 5,
) -> None:
    """
    Orchestrate market data subscriptions.

    This function initializes connections, subscribes to market data feeds,
    performs gap-fill operations, and runs until interrupted.

    Lifted from devtools/playground_testbench.ipynb cells 2, 4, and 5.

    Args:
        symbols: List of symbols to subscribe to (e.g., ["AAPL", "SPY", "QQQ"])
        intervals: List of candle intervals (e.g., ["1d", "1h", "5m", "m"])
        start_date: Date to begin historical backfill
        env_file: Path to .env file for configuration
        lookback_days: Number of days to look back for gap-fill (default: 5)
    """
    dxlink: DXLinkManager | None = None

    try:
        # === Service Connections (notebook cell-2) ===
        logger.info("Initializing configuration from %s", env_file)
        config = RedisConfigManager(env_file=env_file)
        config.initialize(force=True)

        credentials = Credentials(config=config, env="Live")

        logger.info("Opening DXLink connection")
        dxlink = DXLinkManager(subscription_store=RedisSubscriptionStore())
        await dxlink.open(credentials=credentials)

        # Attach processors to all handlers
        router = dxlink.router
        if router is None:
            raise RuntimeError("DXLink router not initialized after open()")

        handlers_dict = getattr(router, "handler", None)
        if handlers_dict is None:
            raise RuntimeError("DXLink router.handler mapping not initialized")

        for handler in handlers_dict.values():
            handler.add_processor(TelegrafHTTPEventProcessor())
            handler.add_processor(RedisEventProcessor())

        logger.info("Processors attached to all handlers")

        # === Market Data Subscriptions (notebook cell-4) ===
        # Ticker subscriptions (Quote/Trade/Greeks)
        logger.info("Subscribing to ticker feeds for %d symbols", len(symbols))
        await dxlink.subscribe(symbols)

        # Candle subscriptions with historical backfill
        total_candle_feeds = len(symbols) * len(intervals)
        start_date_str = start_date.strftime("%Y-%m-%d")
        # Set up snapshot tracker with per-symbol gap-fill via completions queue
        candle_handler = handlers_dict.get(Channels.Candle)
        if candle_handler is None:
            raise RuntimeError("Candle handler not found in router")

        snapshot_tracker = CandleSnapshotTracker()

        for symbol in symbols:
            for interval in intervals:
                event_symbol = format_candle_symbol(f"{symbol}{{={interval}}}")
                snapshot_tracker.register_symbol(event_symbol)

        candle_handler.add_processor(snapshot_tracker)
        logger.info(
            "Subscribing to %d candle feeds from %s",
            total_candle_feeds,
            start_date_str,
        )

        successful = 0
        failed = 0
        for symbol in symbols:
            for interval in intervals:
                logger.debug(
                    "Subscribing %s %s from %s", symbol, interval, start_date_str
                )
                try:
                    await asyncio.wait_for(
                        dxlink.subscribe_to_candles(
                            symbol=symbol,
                            interval=interval,
                            from_time=start_date,
                        ),
                        timeout=60,
                    )
                    successful += 1
                except asyncio.TimeoutError:
                    failed += 1
                    logger.warning(
                        "Backfill timeout: %s %s (exceeded 60s)", symbol, interval
                    )
                except Exception as e:
                    failed += 1
                    logger.error("Backfill error: %s %s - %s", symbol, interval, e)

        if failed > 0:
            logger.warning(
                "Subscribed %d/%d feeds (%d failed)",
                successful,
                total_candle_feeds,
                failed,
            )

        # === Gap Fill — runs per-symbol as each snapshot completes ===
        snapshot_timeout = max(60.0, total_candle_feeds * 5.0)
        logger.info("Waiting for snapshots and loading data...")

        async def gap_fill_consumer() -> int:
            """Drain the completions queue, gap-filling each symbol immediately."""
            filled = 0
            while True:
                event_symbol = await snapshot_tracker.completions.get()
                await asyncio.to_thread(
                    forward_fill, symbol=event_symbol, lookback_days=lookback_days
                )
                filled += 1
                logger.info(
                    "Loaded %s (%d/%d)",
                    event_symbol,
                    filled,
                    total_candle_feeds,
                )
                snapshot_tracker.completions.task_done()

        consumer_task = asyncio.create_task(gap_fill_consumer())

        incomplete = await snapshot_tracker.wait_for_completion(
            timeout=snapshot_timeout
        )
        if incomplete:
            logger.warning(
                "%d incomplete snapshots (gap-fill skipped): %s",
                len(incomplete),
                sorted(incomplete),
            )

        # Wait for queued gap-fills to finish, then cancel the consumer
        await snapshot_tracker.completions.join()
        consumer_task.cancel()

        candle_handler.remove_processor(snapshot_tracker)
        logger.info(
            "Gap-fill complete for %d/%d feeds",
            len(snapshot_tracker.completed_symbols),
            total_candle_feeds,
        )

        # === Run until interrupted ===
        logger.info("Subscription active - press Ctrl+C to stop")
        while True:
            await asyncio.sleep(3600)

    finally:
        if dxlink is not None:
            logger.info("Closing DXLink connection")
            await dxlink.close()
            logger.info("Cleanup complete")
