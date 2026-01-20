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
from tastytrade.messaging.processors import (
    RedisEventProcessor,
    TelegrafHTTPEventProcessor,
)
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
        logger.info(
            "Subscribing to %d candle feeds (from %s)",
            total_candle_feeds,
            start_date.strftime("%Y-%m-%d"),
        )

        for symbol in symbols:
            for interval in intervals:
                await asyncio.wait_for(
                    dxlink.subscribe_to_candles(
                        symbol=symbol,
                        interval=interval,
                        from_time=start_date,
                    ),
                    timeout=60,
                )

        logger.info("All subscriptions active")

        # === Gap Fill (notebook cell-5) ===
        logger.info("Running gap-fill with %d day lookback", lookback_days)
        for symbol in symbols:
            for interval in intervals:
                event_symbol = f"{symbol}{{={interval}}}"
                logger.debug("Forward-filling %s", event_symbol)
                forward_fill(symbol=event_symbol, lookback_days=lookback_days)

        logger.info("Gap-fill complete")

        # === Run until interrupted ===
        logger.info("Subscription active - press Ctrl+C to stop")
        while True:
            await asyncio.sleep(3600)

    finally:
        if dxlink is not None:
            logger.info("Closing DXLink connection")
            await dxlink.close()
            logger.info("Cleanup complete")
