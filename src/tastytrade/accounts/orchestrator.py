"""Account stream orchestrator with self-healing reconnection.

Runs the AccountStreamer, publishes events to Redis via AccountStreamPublisher,
and self-heals with exponential backoff on connection failures.

Mirrors the pattern from ``subscription.orchestrator.run_subscription``.
"""

import asyncio
import logging
import time

from tastytrade.accounts.models import InstrumentType, Position
from tastytrade.accounts.publisher import AccountStreamPublisher, Instrument
from tastytrade.accounts.streamer import AccountStreamer
from tastytrade.config import RedisConfigManager
from tastytrade.config.enumerations import AccountEventType
from tastytrade.connections import Credentials
from tastytrade.market.instruments import InstrumentsClient

logger = logging.getLogger(__name__)

# Minimum seconds a connection must be alive before failure resets retry counter
HEALTHY_CONNECTION_THRESHOLD = 60


class AccountStreamError(Exception):
    """Wraps account stream failures with health context for retry logic."""

    def __init__(self, message: str, was_healthy: bool = False) -> None:
        super().__init__(message)
        self.was_healthy = was_healthy


async def _consume_positions(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
) -> None:
    """Drain Position events from the queue and publish to Redis."""
    while True:
        position = await queue.get()
        await publisher.publish_position(position)


async def _consume_balances(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
) -> None:
    """Drain AccountBalance events from the queue and publish to Redis."""
    while True:
        balance = await queue.get()
        await publisher.publish_balance(balance)


async def _consume_orders(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
) -> None:
    """Drain Order events from the queue and publish to Redis."""
    while True:
        order = await queue.get()
        await publisher.publish_order(order)


async def _consume_complex_orders(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
) -> None:
    """Drain ComplexOrder events from the queue and publish to Redis."""
    while True:
        order = await queue.get()
        await publisher.publish_complex_order(order)


async def run_account_stream_once(
    env_file: str = ".env",
    health_interval: int = 3600,
) -> None:
    """Run a single account stream session without retry logic.

    Connects to the TastyTrade Account Streamer WebSocket, publishes
    CurrentPosition and AccountBalance events to Redis, and monitors
    for reconnection signals.

    Args:
        env_file: Path to .env file for configuration.
        health_interval: Seconds between health status log entries.

    Raises:
        AccountStreamError: On connection or streaming failure.
        asyncio.CancelledError: On user cancellation (propagated).
    """
    streamer: AccountStreamer | None = None
    publisher: AccountStreamPublisher | None = None
    consumer_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]
    connection_established_at: float | None = None

    try:
        # === Configuration ===
        logger.info("Initializing configuration from %s", env_file)
        config = RedisConfigManager(env_file=env_file)
        config.initialize(force=True)

        env_setting = config.get("ENVIRONMENT", "LIVE").upper()
        env = "Live" if env_setting == "LIVE" else "Test"
        credentials = Credentials(config=config, env=env)
        logger.info("Using %s environment (%s)", env, credentials.base_url)

        # === Reset and create AccountStreamer ===
        AccountStreamer.instance = None
        streamer = AccountStreamer(credentials=credentials)
        await streamer.start()
        logger.info("AccountStreamer started")

        # === Create publisher ===
        publisher = AccountStreamPublisher()

        # === Enrich positions with instrument details ===
        position_queue = streamer.queues[AccountEventType.CURRENT_POSITION]
        hydrated_items = []
        while not position_queue.empty():
            hydrated_items.append(position_queue.get_nowait())

        hydrated_positions = [p for p in hydrated_items if isinstance(p, Position)]

        if streamer.session is not None and hydrated_positions:
            instruments_client = InstrumentsClient(streamer.session)

            equity_option_syms = [
                p.symbol
                for p in hydrated_positions
                if p.instrument_type == InstrumentType.EQUITY_OPTION
            ]
            future_option_syms = [
                p.symbol
                for p in hydrated_positions
                if p.instrument_type == InstrumentType.FUTURE_OPTION
            ]
            equity_syms = [
                p.symbol
                for p in hydrated_positions
                if p.instrument_type == InstrumentType.EQUITY
            ]
            future_syms = [
                p.symbol
                for p in hydrated_positions
                if p.instrument_type == InstrumentType.FUTURE
            ]
            # Also fetch underlying futures for future option positions
            # so we have their notional-multiplier for P&L calculations.
            future_option_underlying_syms = list(
                {
                    p.underlying_symbol
                    for p in hydrated_positions
                    if p.instrument_type == InstrumentType.FUTURE_OPTION
                    and p.underlying_symbol
                    and p.underlying_symbol not in future_syms
                }
            )
            future_syms = future_syms + future_option_underlying_syms
            crypto_syms = [
                p.symbol
                for p in hydrated_positions
                if p.instrument_type == InstrumentType.CRYPTOCURRENCY
            ]

            all_instruments: list[Instrument] = []
            if equity_option_syms:
                all_instruments += await instruments_client.get_equity_options(
                    equity_option_syms
                )
            if future_option_syms:
                all_instruments += await instruments_client.get_future_options(
                    future_option_syms
                )
            if equity_syms:
                all_instruments += await instruments_client.get_equities(equity_syms)
            if future_syms:
                all_instruments += await instruments_client.get_futures(future_syms)
            if crypto_syms:
                all_instruments += await instruments_client.get_cryptocurrencies(
                    crypto_syms
                )

            await publisher.publish_instruments(all_instruments)
            logger.info("Enriched positions with %d instruments", len(all_instruments))

        for item in hydrated_items:
            position_queue.put_nowait(item)

        # === Start consumer tasks for position + balance queues ===
        balance_queue = streamer.queues[AccountEventType.ACCOUNT_BALANCE]

        consumer_tasks.append(
            asyncio.create_task(
                _consume_positions(position_queue, publisher),
                name="position_consumer",
            )
        )
        consumer_tasks.append(
            asyncio.create_task(
                _consume_balances(balance_queue, publisher),
                name="balance_consumer",
            )
        )

        # === Start consumer tasks for order + complex order queues ===
        order_queue = streamer.queues[AccountEventType.ORDER]
        complex_order_queue = streamer.queues[AccountEventType.COMPLEX_ORDER]

        consumer_tasks.append(
            asyncio.create_task(
                _consume_orders(order_queue, publisher),
                name="order_consumer",
            )
        )
        consumer_tasks.append(
            asyncio.create_task(
                _consume_complex_orders(complex_order_queue, publisher),
                name="complex_order_consumer",
            )
        )

        connection_established_at = time.monotonic()
        logger.info("Account stream active - press Ctrl+C to stop")

        # === Monitor for reconnection signal ===
        while True:
            sleep_task = asyncio.create_task(asyncio.sleep(health_interval))
            monitor_task = asyncio.create_task(streamer.wait_for_reconnect_signal())

            done, pending = await asyncio.wait(
                [monitor_task, sleep_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            if monitor_task in done:
                reason = monitor_task.result()
                logger.warning("Reconnection triggered: %s", reason.value)
                raise ConnectionError(f"Reconnection triggered: {reason.value}")

            # Health check on interval
            uptime = int(time.monotonic() - connection_established_at)
            logger.info(
                "Health -- Account stream uptime: %ds | consumers: %d",
                uptime,
                len(consumer_tasks),
            )

    except asyncio.CancelledError:
        raise
    except Exception as e:
        was_healthy = (
            connection_established_at is not None
            and (time.monotonic() - connection_established_at)
            > HEALTHY_CONNECTION_THRESHOLD
        )
        raise AccountStreamError(str(e), was_healthy=was_healthy) from e
    finally:
        # Cancel consumer tasks
        for task in consumer_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if streamer is not None:
            logger.info("Closing AccountStreamer")
            await streamer.close()

        if publisher is not None:
            logger.info("Closing AccountStreamPublisher")
            await publisher.close()

        logger.info("Account stream cleanup complete")


async def run_account_stream(
    env_file: str = ".env",
    health_interval: int = 3600,
    auto_reconnect: bool = True,
    max_reconnect_attempts: int = 10,
    base_delay: float = 1.0,
    max_delay: float = 300.0,
) -> None:
    """Run account stream with optional automatic reconnection.

    Self-healing wrapper around ``run_account_stream_once`` with exponential
    backoff. Mirrors the pattern from ``subscription.orchestrator.run_subscription``.

    Args:
        env_file: Path to .env file for configuration.
        health_interval: Seconds between health status log entries.
        auto_reconnect: If True, automatically retry on connection failures
                       with exponential backoff. If False, exit on first failure
                       (useful for testing). Default: True.
        max_reconnect_attempts: Maximum number of reconnection attempts.
        base_delay: Initial delay in seconds between reconnection attempts.
        max_delay: Maximum delay in seconds between reconnection attempts.
    """
    if not auto_reconnect:
        await run_account_stream_once(
            env_file=env_file,
            health_interval=health_interval,
        )
        return

    attempt = 0

    while attempt < max_reconnect_attempts:
        try:
            await run_account_stream_once(
                env_file=env_file,
                health_interval=health_interval,
            )
            break  # Clean exit
        except asyncio.CancelledError:
            logger.info("Account stream cancelled by user")
            raise  # User interrupt - don't reconnect
        except AccountStreamError as e:
            if e.was_healthy:
                logger.info(
                    "Connection was healthy before failure, resetting retry counter"
                )
                attempt = 0
            else:
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
            "Max reconnection attempts (%d) reached, giving up",
            max_reconnect_attempts,
        )
