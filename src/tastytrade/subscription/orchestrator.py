"""
Market data subscription orchestrator.

This module provides the orchestration logic for market data subscriptions,
extracted from devtools/playground_testbench.ipynb for CLI integration.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from tastytrade.config import RedisConfigManager
from tastytrade.config.enumerations import Channels
from tastytrade.connections import Credentials
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.connections.subscription import RedisSubscriptionStore
from tastytrade.messaging.processors import (
    CandleSnapshotTracker,
    RedisEventProcessor,
    TelegrafHTTPEventProcessor,
)
from tastytrade.utils.helpers import format_candle_symbol
from tastytrade.utils.time_series import forward_fill

logger = logging.getLogger(__name__)

# Backfill buffer for candle restoration after reconnect
BACKFILL_BUFFER = timedelta(hours=1)

# Regex pattern to extract symbol and interval from candle symbol like "AAPL{=1d}"
CANDLE_SYMBOL_PATTERN = re.compile(r"^(.+)\{=(.+)\}$")


def format_uptime(seconds: float) -> str:
    """Format elapsed seconds as a human-readable uptime string."""
    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def extract_candle_parts(symbol: str) -> tuple[str, str] | None:
    """Extract base symbol and interval from candle symbol like 'AAPL{=1d}'.

    Returns:
        Tuple of (base_symbol, interval) or None if not a candle symbol.
    """
    match = CANDLE_SYMBOL_PATTERN.match(symbol)
    if match:
        return match.group(1), match.group(2)
    return None


async def restore_subscriptions(dxlink: DXLinkManager) -> int:
    """
    Restore previously active subscriptions after reconnect.

    Retrieves subscriptions from the Redis store and re-subscribes.
    For candle subscriptions, uses a 1-hour backfill buffer from last_update.

    Args:
        dxlink: The DXLinkManager instance to restore subscriptions on.

    Returns:
        Number of subscriptions restored.
    """
    active: Dict[str, Any] = await dxlink.subscription_store.get_active_subscriptions()

    if not active:
        logger.info("No active subscriptions to restore")
        return 0

    # Separate ticker vs candle subscriptions
    tickers = [s for s in active if "{=" not in s]
    candles = [s for s in active if "{=" in s]

    restored = 0

    # Restore ticker subscriptions (Quote/Trade/Greeks)
    if tickers:
        await dxlink.subscribe(tickers)
        restored += len(tickers)
        logger.info("Restored %d ticker subscriptions", len(tickers))

    # Restore candle subscriptions with backfill
    for symbol in candles:
        parts = extract_candle_parts(symbol)
        if not parts:
            logger.warning("Could not parse candle symbol: %s", symbol)
            continue

        base_symbol, interval = parts

        # Determine backfill start time
        metadata = active.get(symbol, {})
        last_update_str = (
            metadata.get("last_update") if isinstance(metadata, dict) else None
        )

        if last_update_str:
            try:
                last_update = datetime.fromisoformat(last_update_str)
                from_time = last_update - BACKFILL_BUFFER
            except (ValueError, TypeError):
                from_time = datetime.now(timezone.utc) - BACKFILL_BUFFER
        else:
            from_time = datetime.now(timezone.utc) - BACKFILL_BUFFER

        await dxlink.subscribe_to_candles(base_symbol, interval, from_time)
        restored += 1
        logger.info("Restored %s from %s", symbol, from_time.isoformat())

    logger.info("Restored %d total subscriptions", restored)
    return restored


async def run_subscription(
    symbols: list[str],
    intervals: list[str],
    start_date: datetime,
    env_file: str = ".env",
    lookback_days: int = 5,
    health_interval: int = 300,
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
        health_interval: Seconds between health log entries (default: 300)
    """
    dxlink: DXLinkManager | None = None
    session_symbols: set[str] = set()

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
        session_symbols.update(symbols)

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
                    event_symbol = format_candle_symbol(f"{symbol}{{={interval}}}")
                    session_symbols.add(event_symbol)
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
            "Subscription and back-fill complete for %d/%d subscriptions",
            len(snapshot_tracker.completed_symbols),
            total_candle_feeds,
        )

        # === Run until interrupted — periodic health check ===
        logger.info("Subscription active - press Ctrl+C to stop")
        start_time = time.monotonic()

        while True:
            await asyncio.sleep(health_interval)

            uptime = format_uptime(time.monotonic() - start_time)
            feed_count = sum(
                h.metrics.total_messages > 0 for h in handlers_dict.values()
            )
            logger.info("Health — Uptime: %s | %d channels active", uptime, feed_count)

    finally:
        if dxlink is not None:
            # Mark this session's subscriptions as inactive in Redis
            if session_symbols:
                logger.info(
                    "Marking %d session subscriptions inactive", len(session_symbols)
                )
                for sym in session_symbols:
                    try:
                        await dxlink.subscription_store.remove_subscription(sym)
                    except Exception as e:
                        logger.warning("Failed to deactivate %s: %s", sym, e)

            # Flush all processors before closing DXLink
            # This ensures InfluxDB batched writes are flushed
            if dxlink.router is not None:
                logger.info("Flushing processors...")
                for handler in dxlink.router.handler.values():
                    handler.close_processors()

            logger.info("Closing DXLink connection")
            await dxlink.close()
            logger.info("Cleanup complete")


async def run_subscription_with_reconnect(
    symbols: list[str],
    intervals: list[str],
    start_date: datetime,
    max_reconnect_attempts: int = 10,
    base_delay: float = 1.0,
    max_delay: float = 300.0,
    **kwargs: object,
) -> None:
    """
    Run subscription with automatic reconnection on failure.

    Wraps run_subscription with exponential backoff reconnection logic.

    Args:
        symbols: List of symbols to subscribe to
        intervals: List of candle intervals
        start_date: Date to begin historical backfill
        max_reconnect_attempts: Maximum number of reconnection attempts (default: 10)
        base_delay: Initial delay in seconds between reconnection attempts (default: 1.0)
        max_delay: Maximum delay in seconds between reconnection attempts (default: 300.0)
        **kwargs: Additional arguments passed to run_subscription
    """
    attempt = 0

    while attempt < max_reconnect_attempts:
        try:
            await run_subscription(
                symbols,
                intervals,
                start_date,
                **kwargs,  # type: ignore[arg-type]
            )
            break  # Clean exit
        except asyncio.CancelledError:
            logger.info("Subscription cancelled by user")
            raise  # User interrupt - don't reconnect
        except Exception as e:
            attempt += 1
            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                "Connection failed (attempt %d/%d): %s. Reconnecting in %.1fs",
                attempt,
                max_reconnect_attempts,
                e,
                delay,
            )
            await asyncio.sleep(delay)
    else:
        logger.error(
            "Max reconnection attempts (%d) reached, giving up", max_reconnect_attempts
        )
