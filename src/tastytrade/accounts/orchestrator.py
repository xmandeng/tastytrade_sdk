"""Account stream orchestrator with self-healing reconnection.

Runs the AccountStreamer, publishes events to Redis via AccountStreamPublisher,
and self-heals with exponential backoff on connection failures.

Mirrors the pattern from ``subscription.orchestrator.run_subscription``.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import redis.asyncio as aioredis  # type: ignore[import-untyped]
from pydantic import ValidationError

from tastytrade.accounts.models import (
    InstrumentType,
    OrderAction,
    OrderLeg,
    OrderStatus,
    PlacedOrder,
    Position,
    TradeChain,
)
from tastytrade.accounts.publisher import AccountStreamPublisher, Instrument
from tastytrade.accounts.streamer import AccountStreamer
from tastytrade.accounts.transactions import (
    EntryCredit,
    TransactionsClient,
    compute_entry_credits_for_positions,
)
from tastytrade.config import RedisConfigManager
from tastytrade.config.enumerations import AccountEventType, ReconnectReason
from tastytrade.connections import Credentials
from tastytrade.connections.signals import ReconnectSignal
from tastytrade.market.instruments import InstrumentsClient
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor

logger = logging.getLogger(__name__)

# Minimum seconds a connection must be alive before failure resets retry counter
HEALTHY_CONNECTION_THRESHOLD = 60


class AccountStreamError(Exception):
    """Wraps account stream failures with health context for retry logic."""

    def __init__(self, message: str, was_healthy: bool = False) -> None:
        super().__init__(message)
        self.was_healthy = was_healthy


async def update_account_connection_status(
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
    state: str,
    reason: str | None = None,
) -> None:
    """Update account connection status in Redis for external monitoring."""
    status: dict[str, str] = {
        "state": state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        status["error"] = reason
    await redis_client.hset("tastytrade:account_connection", mapping=status)  # type: ignore[arg-type]

    # Clear stale error field when connection is healthy
    if not reason:
        await redis_client.hdel("tastytrade:account_connection", "error")


async def consume_positions(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
    influx: TelegrafHTTPEventProcessor,
    stop: asyncio.Event,
) -> None:
    """Drain Position events from the queue and publish to Redis + InfluxDB."""
    while not stop.is_set():
        try:
            position = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        await publisher.publish_position(position)
        influx.process_event(position.for_influx())  # type: ignore[arg-type]


async def consume_balances(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
    stop: asyncio.Event,
) -> None:
    """Drain AccountBalance events from the queue and publish to Redis."""
    while not stop.is_set():
        try:
            balance = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        await publisher.publish_balance(balance)


async def consume_orders(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
    influx: TelegrafHTTPEventProcessor,
    stop: asyncio.Event,
) -> None:
    """Drain Order events from the queue and publish to Redis + InfluxDB."""
    while not stop.is_set():
        try:
            order = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        await publisher.publish_order(order)
        influx.process_event(order.for_influx())  # type: ignore[arg-type]


async def consume_complex_orders(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
    influx: TelegrafHTTPEventProcessor,
    stop: asyncio.Event,
) -> None:
    """Drain ComplexOrder events from the queue and publish to Redis + InfluxDB."""
    while not stop.is_set():
        try:
            order = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        await publisher.publish_complex_order(order)
        influx.process_event(order.for_influx())  # type: ignore[arg-type]


def safe_float(value: str | None) -> float | None:
    """Convert an optional string to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def extract_execution_greeks(
    chain: TradeChain,
) -> list[SimpleNamespace]:
    """Extract flat, queryable InfluxDB points from TradeChain market snapshots.

    Produces two types of points per node that has a market-state-snapshot:
    - ExecutionGreeks: one per option leg with per-leg Greeks + spot prices
    - ExecutionGreeksAggregate: one per node with total_delta, total_theta
    """
    points: list[SimpleNamespace] = []

    for node in chain.lite_nodes:
        snapshot = node.market_state_snapshot
        if snapshot is None:
            continue

        occurred_at = node.occurred_at
        if occurred_at is None:
            continue
        node_time = datetime.fromisoformat(occurred_at)

        # Find underlying spot prices from the snapshot
        underlying_bid: float | None = None
        underlying_ask: float | None = None
        underlying_last: float | None = None
        for md in snapshot.market_datas:
            if md.delta is None and md.gamma is None:
                # Non-option instrument = underlying
                underlying_bid = safe_float(md.bid)
                underlying_ask = safe_float(md.ask)
                underlying_last = safe_float(md.last)
                break

        # Per-leg points
        for md in snapshot.market_datas:
            # Skip the underlying — it has no Greeks
            if md.delta is None and md.gamma is None:
                continue

            leg_cls = type("ExecutionGreeks", (SimpleNamespace,), {})
            points.append(
                leg_cls(
                    eventSymbol=md.symbol,
                    time=node_time,
                    chain_id=chain.id,
                    underlying=chain.underlying_symbol,
                    strategy=chain.description,
                    node_description=node.description,
                    delta=safe_float(md.delta),
                    gamma=safe_float(md.gamma),
                    theta=safe_float(md.theta),
                    vega=safe_float(md.vega),
                    rho=safe_float(md.rho),
                    bid=safe_float(md.bid),
                    ask=safe_float(md.ask),
                    last=safe_float(md.last),
                    underlying_bid=underlying_bid,
                    underlying_ask=underlying_ask,
                    underlying_last=underlying_last,
                ),
            )

        # Aggregate point
        agg_cls = type("ExecutionGreeksAggregate", (SimpleNamespace,), {})
        points.append(
            agg_cls(
                eventSymbol=chain.underlying_symbol,
                time=node_time,
                chain_id=chain.id,
                strategy=chain.description,
                node_description=node.description,
                total_delta=safe_float(snapshot.total_delta),
                total_theta=safe_float(snapshot.total_theta),
                underlying_bid=underlying_bid,
                underlying_ask=underlying_ask,
                underlying_last=underlying_last,
            ),
        )

    return points


async def consume_order_chains(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
    influx: TelegrafHTTPEventProcessor,
    stop: asyncio.Event,
) -> None:
    """Drain OrderChain events from the queue and publish to Redis + InfluxDB."""
    while not stop.is_set():
        try:
            chain = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        await publisher.publish_trade_chain(chain)
        influx.process_event(chain.for_influx())  # type: ignore[arg-type]
        for greeks_point in extract_execution_greeks(chain):
            influx.process_event(greeks_point)  # type: ignore[arg-type]


OPTION_TYPES = {InstrumentType.EQUITY_OPTION, InstrumentType.FUTURE_OPTION}
OPEN_ACTIONS = {OrderAction.BUY_TO_OPEN, OrderAction.SELL_TO_OPEN}


async def resolve_multiplier(
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
    leg: OrderLeg,
) -> Decimal:
    """Resolve the contract multiplier for an option leg from the Position in Redis.

    The Position API always populates ``multiplier`` for options:
    100 for equity options, notional multiplier for future options
    (e.g. 100 for /GC, 125000 for /6E, 50 for /RTY).

    The position consumer and fill monitor run concurrently, so the
    position may not be in Redis yet when a fill arrives. Retries
    briefly to allow the position event to land.
    """
    for _ in range(5):
        raw = await redis_client.hget(AccountStreamPublisher.POSITIONS_KEY, leg.symbol)
        if raw is not None:
            position = json.loads(raw)
            m = position.get("multiplier")
            if m is not None:
                return Decimal(str(m))
        await asyncio.sleep(0.2)

    logger.warning(
        "Position not found in Redis for %s, using default multiplier", leg.symbol
    )

    # Equity options default to 100 shares per contract
    if leg.instrument_type == InstrumentType.EQUITY_OPTION:
        return Decimal("100")

    return Decimal("1")


def compute_leg_entry_credit(leg: OrderLeg, multiplier: Decimal) -> EntryCredit:
    """Compute entry credit for a single option leg from its fill data.

    Uses the fill prices and quantities directly from the order event.
    Sign convention: Sell to Open = credit (positive), Buy to Open = debit (negative).
    """
    sign = Decimal("1") if leg.action == OrderAction.SELL_TO_OPEN else Decimal("-1")

    total_value = Decimal("0")
    total_qty = Decimal("0")
    price_x_qty = Decimal("0")

    for fill in leg.fills:
        fp = Decimal(str(fill.fill_price))
        fq = Decimal(str(fill.quantity))
        total_value += fp * fq * multiplier * sign
        total_qty += fq
        price_x_qty += fp * fq

    weighted_price = price_x_qty / total_qty if total_qty > 0 else None

    return EntryCredit(
        symbol=leg.symbol,
        value=total_value,
        per_unit_price=weighted_price,
        method="order_fill",
        transaction_count=len(leg.fills),
        computed_at=datetime.now(timezone.utc),
    )


async def monitor_fills_for_entry_credits(
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
    publisher: AccountStreamPublisher,
    influx: TelegrafHTTPEventProcessor,
) -> None:
    """Compute entry credits directly from filled order data.

    Subscribes to the Order pub/sub channel. When a FILLED order with option
    open-fills is detected, computes entry credits from the fill prices in
    the order event itself — no position lookup or REST API call needed.

    Close fills are ignored; position removal is handled by the position
    consumer (publish_position removes qty=0 positions from Redis).
    """
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(publisher.ORDER_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                order = PlacedOrder.model_validate_json(message["data"])
            except ValidationError:
                logger.warning("Failed to parse Order event, skipping message")
                continue

            if order.status != OrderStatus.FILLED:
                continue

            # Compute entry credits for option legs with open fills.
            # Close fills are ignored — position removal handles cleanup.
            entry_credits: dict[str, EntryCredit] = {}
            for leg in order.legs:
                if leg.instrument_type not in OPTION_TYPES:
                    continue
                if leg.action not in OPEN_ACTIONS:
                    continue
                if not leg.fills:
                    continue

                multiplier = await resolve_multiplier(redis_client, leg)
                credit = compute_leg_entry_credit(leg, multiplier)
                entry_credits[leg.symbol] = credit

            if entry_credits:
                await publisher.publish_entry_credits(entry_credits)
                for credit in entry_credits.values():
                    influx.process_event(credit.for_influx())  # type: ignore[arg-type]
                logger.info(
                    "Computed entry credits for %d symbols from fill data",
                    len(entry_credits),
                )

    finally:
        await pubsub.unsubscribe(publisher.ORDER_CHANNEL)
        await pubsub.close()


async def account_failure_trigger_listener(
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
    reconnect_signal: ReconnectSignal,
) -> None:
    """Listen for failure simulation commands via Redis pub/sub.

    Subscribes to 'account:simulate_failure' channel and triggers
    reconnection when a valid ReconnectReason value is received.

    Args:
        redis_client: Async Redis client for pub/sub.
        reconnect_signal: ReconnectSignal to trigger on valid commands.

    Usage:
        redis-cli PUBLISH account:simulate_failure "connection_dropped"
    """
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("account:simulate_failure")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                reason_str = (
                    message["data"].decode()
                    if isinstance(message["data"], bytes)
                    else message["data"]
                )
                try:
                    reason = ReconnectReason(reason_str)
                    logger.info("Received simulate_failure command: %s", reason.value)
                    reconnect_signal.trigger(reason)
                except ValueError:
                    logger.warning("Invalid ReconnectReason received: %s", reason_str)
    except asyncio.CancelledError:
        logger.info("Account failure trigger listener stopped")
    finally:
        await pubsub.unsubscribe("account:simulate_failure")
        await pubsub.close()


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
    influx: TelegrafHTTPEventProcessor | None = None
    stop = asyncio.Event()
    consumer_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]
    failure_listener_task: asyncio.Task[None] | None = None
    fill_monitor_task: asyncio.Task[None] | None = None
    failure_redis: aioredis.Redis | None = None  # type: ignore[type-arg]
    fill_monitor_redis: aioredis.Redis | None = None  # type: ignore[type-arg]
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
        reconnect_signal = ReconnectSignal()
        streamer = AccountStreamer(
            credentials=credentials, reconnect_signal=reconnect_signal
        )
        await streamer.start()
        logger.info("AccountStreamer started")

        # === Create publisher ===
        publisher = AccountStreamPublisher()

        # === Create InfluxDB processor for time-series persistence (TT-83) ===
        influx = TelegrafHTTPEventProcessor(
            url=config.get("INFLUX_DB_URL", "http://localhost:8086"),
            token=config.get("INFLUX_DB_TOKEN"),
            org=config.get("INFLUX_DB_ORG"),
            bucket=config.get("INFLUX_DB_BUCKET"),
        )
        logger.info("TelegrafHTTPEventProcessor initialized for account events")

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
            # Also fetch underlying futures for futures option positions
            future_option_underlyings = list(
                {
                    p.underlying_symbol
                    for p in hydrated_positions
                    if p.instrument_type == InstrumentType.FUTURE_OPTION
                    and p.underlying_symbol
                }
                - set(future_syms)
            )
            if future_option_underlyings:
                all_instruments += await instruments_client.get_futures(
                    future_option_underlyings
                )
            if crypto_syms:
                all_instruments += await instruments_client.get_cryptocurrencies(
                    crypto_syms
                )

            await publisher.publish_instruments(all_instruments)
            logger.info("Enriched positions with %d instruments", len(all_instruments))

            # === Compute entry credits from transaction history ===
            option_positions = [
                p
                for p in hydrated_positions
                if p.instrument_type
                in (InstrumentType.EQUITY_OPTION, InstrumentType.FUTURE_OPTION)
            ]
            if option_positions:
                account_number = credentials.account_number
                txn_client = TransactionsClient(streamer.session)
                all_txns = await txn_client.get_transactions(account_number)
                positions_map: dict[str, int] = {}
                for p in option_positions:
                    positions_map[p.symbol] = int(abs(p.quantity))

                entry_credits = compute_entry_credits_for_positions(
                    all_txns, positions_map
                )
                await publisher.publish_entry_credits(entry_credits)
                for credit in entry_credits.values():
                    influx.process_event(credit.for_influx())  # type: ignore[arg-type]

        for item in hydrated_items:
            position_queue.put_nowait(item)

        # === Start consumer tasks for position + balance queues ===
        balance_queue = streamer.queues[AccountEventType.ACCOUNT_BALANCE]

        consumer_tasks.append(
            asyncio.create_task(
                consume_positions(position_queue, publisher, influx, stop),
                name="position_consumer",
            )
        )
        consumer_tasks.append(
            asyncio.create_task(
                consume_balances(balance_queue, publisher, stop),
                name="balance_consumer",
            )
        )

        # === Start consumer tasks for order + complex order + order chain queues ===
        order_queue = streamer.queues[AccountEventType.ORDER]
        complex_order_queue = streamer.queues[AccountEventType.COMPLEX_ORDER]
        order_chain_queue = streamer.queues[AccountEventType.ORDER_CHAIN]

        consumer_tasks.append(
            asyncio.create_task(
                consume_orders(order_queue, publisher, influx, stop),
                name="order_consumer",
            )
        )
        consumer_tasks.append(
            asyncio.create_task(
                consume_complex_orders(complex_order_queue, publisher, influx, stop),
                name="complex_order_consumer",
            )
        )
        consumer_tasks.append(
            asyncio.create_task(
                consume_order_chains(order_chain_queue, publisher, influx, stop),
                name="order_chain_consumer",
            )
        )

        # === Start fill monitor for live entry credit updates (TT-79/TT-87) ===
        fill_monitor_redis = aioredis.Redis()
        fill_monitor_task = asyncio.create_task(
            monitor_fills_for_entry_credits(
                redis_client=fill_monitor_redis,
                publisher=publisher,
                influx=influx,
            ),
            name="fill_monitor",
        )
        logger.info("Fill monitor started for live entry credit updates")

        # === Start failure simulation listener ===
        failure_redis = aioredis.Redis()
        failure_listener_task = asyncio.create_task(
            account_failure_trigger_listener(failure_redis, reconnect_signal),
            name="account_failure_listener",
        )

        connection_established_at = time.monotonic()
        logger.info("Account stream active - press Ctrl+C to stop")
        await update_account_connection_status(publisher.redis, state="connected")

        # === Monitor for reconnection signal ===
        while True:
            sleep_task = asyncio.create_task(asyncio.sleep(health_interval))
            monitor_task = asyncio.create_task(reconnect_signal.wait())

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
                await update_account_connection_status(
                    publisher.redis, state="error", reason=reason.value
                )
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
        # Signal consumers to stop gracefully
        stop.set()

        # Cancel failure listener task
        if failure_listener_task is not None:
            failure_listener_task.cancel()
            try:
                await failure_listener_task
            except asyncio.CancelledError:
                pass

        # Close failure listener Redis client
        if failure_redis is not None:
            await failure_redis.close()

        # Cancel fill monitor task
        if fill_monitor_task is not None:
            fill_monitor_task.cancel()
            try:
                await fill_monitor_task
            except asyncio.CancelledError:
                pass

        # Close fill monitor Redis client
        if fill_monitor_redis is not None:
            await fill_monitor_redis.close()

        # Cancel consumer tasks
        for task in consumer_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Close InfluxDB processor (TT-83)
        if influx is not None:
            influx.close()

        if streamer is not None:
            logger.info("Closing AccountStreamer")
            await streamer.close()

        if publisher is not None:
            await update_account_connection_status(
                publisher.redis, state="disconnected"
            )
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
