# TT-59: Position Metrics Pipeline — Implementation Plan

> **Jira:** [TT-59](https://tastytrade-sdk.atlassian.net/browse/TT-59) — Integrate AccountStreamer into subscription service with position-driven DXLink subscriptions
>
> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build decomposable backend services that stream account and market data to Redis, with a position metrics reader that is a pure Redis consumer.

**Architecture:** AccountStreamer publishes positions/balances to Redis HSET. Position changes drive DXLink subscriptions for streamer symbols. RedisEventProcessor stores latest Quote/Greeks in HSET (not just pub/sub). The position metrics operation reads everything from Redis — no API or socket calls. All streams self-heal with exponential backoff.

**Tech Stack:** Python 3.12, asyncio, redis (sync + async), pydantic, pandas, click CLI, pytest

---

### Task 1: Enhance RedisEventProcessor — HSET for latest market data

**Files:**
- Modify: `src/tastytrade/messaging/processors/redis.py`
- Test: `unit_tests/messaging/test_redis_event_processor.py` (create)

**Context:** Currently `RedisEventProcessor.process_event()` only does `self.redis.publish()` (pub/sub fire-and-forget). We need to ALSO store the latest event per symbol in a Redis HSET so downstream readers can access it on demand. Pub/sub is preserved — this is additive.

**Redis key design:**
- `tastytrade:latest:QuoteEvent` — HSET, field = eventSymbol, value = JSON
- `tastytrade:latest:GreeksEvent` — HSET, field = eventSymbol, value = JSON
- (Other event types follow same pattern but Quote/Greeks are the priority)

**Step 1: Write the failing test**

```python
# unit_tests/messaging/test_redis_event_processor.py
"""Tests for RedisEventProcessor pub/sub + HSET storage."""

from unittest.mock import MagicMock

from tastytrade.messaging.models.events import GreeksEvent, QuoteEvent
from tastytrade.messaging.processors.redis import RedisEventProcessor


def make_redis_processor() -> RedisEventProcessor:
    """Create a RedisEventProcessor with a mocked Redis client."""
    processor = RedisEventProcessor.__new__(RedisEventProcessor)
    processor.redis = MagicMock()
    processor.pl = __import__("polars").DataFrame()
    processor.frames = {}
    return processor


def test_process_event_publishes_to_channel() -> None:
    processor = make_redis_processor()
    event = QuoteEvent(eventSymbol="SPY", bidPrice=600.0, askPrice=601.0, bidSize=100.0, askSize=200.0)
    processor.process_event(event)
    processor.redis.publish.assert_called_once()
    channel = processor.redis.publish.call_args[1]["channel"]
    assert channel == "market:QuoteEvent:SPY"


def test_process_event_stores_latest_in_hset() -> None:
    processor = make_redis_processor()
    event = QuoteEvent(eventSymbol="SPY", bidPrice=600.0, askPrice=601.0, bidSize=100.0, askSize=200.0)
    processor.process_event(event)
    processor.redis.hset.assert_called_once()
    args = processor.redis.hset.call_args
    assert args[0][0] == "tastytrade:latest:QuoteEvent"
    assert args[0][1] == "SPY"


def test_process_event_stores_greeks_in_hset() -> None:
    processor = make_redis_processor()
    event = GreeksEvent(eventSymbol=".SPY260402P666", delta=-0.24, gamma=0.01, theta=-0.18, vega=0.68, rho=-0.17, volatility=0.19)
    processor.process_event(event)
    processor.redis.hset.assert_called_once()
    args = processor.redis.hset.call_args
    assert args[0][0] == "tastytrade:latest:GreeksEvent"


def test_process_event_latest_overwrites_previous() -> None:
    processor = make_redis_processor()
    event1 = QuoteEvent(eventSymbol="SPY", bidPrice=600.0, askPrice=601.0, bidSize=100.0, askSize=200.0)
    event2 = QuoteEvent(eventSymbol="SPY", bidPrice=605.0, askPrice=606.0, bidSize=100.0, askSize=200.0)
    processor.process_event(event1)
    processor.process_event(event2)
    # HSET called twice for same key — last value wins in Redis
    assert processor.redis.hset.call_count == 2
    last_call = processor.redis.hset.call_args
    assert "605.0" in last_call[0][2] or "605" in last_call[0][2]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest unit_tests/messaging/test_redis_event_processor.py -v`
Expected: FAIL — `hset` not called

**Step 3: Write minimal implementation**

```python
# src/tastytrade/messaging/processors/redis.py
import os

import redis  # type: ignore

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor


class RedisEventProcessor(BaseEventProcessor):
    name = "redis_pubsub"

    def __init__(self, redis_host: str | None = None, redis_port: int | None = None):
        super().__init__()
        host = (
            redis_host
            if redis_host is not None
            else os.environ.get("REDIS_HOST", "localhost")
        )
        port = (
            redis_port
            if redis_port is not None
            else int(os.environ.get("REDIS_PORT", "6379"))
        )
        self.redis = redis.Redis(host=host, port=port)

    def process_event(self, event: BaseEvent) -> None:
        """Process an event: publish to pub/sub AND store latest in HSET."""
        event_json = event.model_dump_json()
        event_type = event.__class__.__name__
        symbol = event.eventSymbol

        # Pub/sub for real-time streaming (existing behavior)
        channel = f"market:{event_type}:{symbol}"
        self.redis.publish(channel=channel, message=event_json)

        # HSET for latest-value reads (new behavior)
        hset_key = f"tastytrade:latest:{event_type}"
        self.redis.hset(hset_key, symbol, event_json)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest unit_tests/messaging/test_redis_event_processor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tastytrade/messaging/processors/redis.py unit_tests/messaging/test_redis_event_processor.py
git commit -m "TT-59: Add HSET storage to RedisEventProcessor for latest market data"
```

---

### Task 2: Create AccountStreamPublisher — publishes account events to Redis

**Files:**
- Create: `src/tastytrade/accounts/publisher.py`
- Test: `unit_tests/accounts/test_account_publisher.py` (create)

**Context:** The `AccountStreamer` puts events into asyncio queues. We need a consumer that reads from those queues and writes to Redis HSET. This is a simple bridge — one responsibility.

**Redis key design:**
- `tastytrade:positions` — HSET, field = streamer_symbol (or symbol if no streamer), value = Position JSON
- `tastytrade:balances` — HSET, field = account_number, value = AccountBalance JSON

**Step 1: Write the failing tests**

```python
# unit_tests/accounts/test_account_publisher.py
"""Tests for AccountStreamPublisher — bridges AccountStreamer queues to Redis."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.accounts.models import AccountBalance, Position
from tastytrade.accounts.publisher import AccountStreamPublisher


def make_position_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": "SPY",
        "instrument-type": "Equity",
        "quantity": "100.0",
        "quantity-direction": "Long",
        "streamer-symbol": "SPY",
    }
    base.update(overrides)
    return base


def make_balance_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "cash-balance": "25000.50",
        "net-liquidating-value": "50000.75",
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def publisher(mock_redis: AsyncMock) -> AccountStreamPublisher:
    pub = AccountStreamPublisher.__new__(AccountStreamPublisher)
    pub.redis = mock_redis
    return pub


def test_position_redis_key() -> None:
    assert AccountStreamPublisher.POSITIONS_KEY == "tastytrade:positions"


def test_balance_redis_key() -> None:
    assert AccountStreamPublisher.BALANCES_KEY == "tastytrade:balances"


@pytest.mark.asyncio
async def test_publish_position_writes_hset(publisher: AccountStreamPublisher, mock_redis: AsyncMock) -> None:
    position = Position.model_validate(make_position_data())
    await publisher.publish_position(position)
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "tastytrade:positions"
    assert call_args[0][1] == "SPY"  # keyed by streamer_symbol


@pytest.mark.asyncio
async def test_publish_position_uses_symbol_when_no_streamer(publisher: AccountStreamPublisher, mock_redis: AsyncMock) -> None:
    position = Position.model_validate(make_position_data(**{"streamer-symbol": None}))
    await publisher.publish_position(position)
    call_args = mock_redis.hset.call_args
    assert call_args[0][1] == "SPY"  # falls back to symbol


@pytest.mark.asyncio
async def test_publish_position_removes_zero_quantity(publisher: AccountStreamPublisher, mock_redis: AsyncMock) -> None:
    position = Position.model_validate(make_position_data(quantity="0.0", **{"quantity-direction": "Zero"}))
    await publisher.publish_position(position)
    mock_redis.hdel.assert_called_once_with("tastytrade:positions", "SPY")


@pytest.mark.asyncio
async def test_publish_balance_writes_hset(publisher: AccountStreamPublisher, mock_redis: AsyncMock) -> None:
    balance = AccountBalance.model_validate(make_balance_data())
    await publisher.publish_balance(balance)
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "tastytrade:balances"
    assert call_args[0][1] == "5WT00001"


@pytest.mark.asyncio
async def test_publish_position_also_publishes_pubsub(publisher: AccountStreamPublisher, mock_redis: AsyncMock) -> None:
    position = Position.model_validate(make_position_data())
    await publisher.publish_position(position)
    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[1]["channel"]
    assert channel == "tastytrade:events:CurrentPosition"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest unit_tests/accounts/test_account_publisher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tastytrade.accounts.publisher'`

**Step 3: Write minimal implementation**

```python
# src/tastytrade/accounts/publisher.py
"""Publishes AccountStreamer events (positions, balances) to Redis.

Reads from AccountStreamer asyncio queues and writes to Redis HSET
for on-demand reads, plus pub/sub for real-time consumers.
Single responsibility: account events → Redis.
"""

import logging
import os
from typing import Optional

import redis.asyncio as aioredis  # type: ignore

from tastytrade.accounts.models import AccountBalance, Position

logger = logging.getLogger(__name__)


class AccountStreamPublisher:
    """Publishes account events to Redis HSET + pub/sub."""

    POSITIONS_KEY = "tastytrade:positions"
    BALANCES_KEY = "tastytrade:balances"

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        self.redis = aioredis.Redis(host=host, port=port)

    async def publish_position(self, position: Position) -> None:
        """Write position to Redis HSET. Remove if quantity is zero (closed)."""
        key = position.streamer_symbol or position.symbol
        if position.quantity == 0.0:
            await self.redis.hdel(self.POSITIONS_KEY, key)
            logger.info("Removed closed position: %s", key)
        else:
            await self.redis.hset(
                self.POSITIONS_KEY, key, position.model_dump_json(by_alias=True)
            )
            await self.redis.publish(
                channel="tastytrade:events:CurrentPosition",
                message=position.model_dump_json(by_alias=True),
            )
            logger.debug("Published position: %s qty=%s", key, position.quantity)

    async def publish_balance(self, balance: AccountBalance) -> None:
        """Write balance to Redis HSET."""
        await self.redis.hset(
            self.BALANCES_KEY,
            balance.account_number,
            balance.model_dump_json(by_alias=True),
        )
        logger.debug("Published balance: %s", balance.account_number)

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest unit_tests/accounts/test_account_publisher.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tastytrade/accounts/publisher.py unit_tests/accounts/test_account_publisher.py
git commit -m "TT-59: Add AccountStreamPublisher for positions/balances to Redis"
```

---

### Task 3: Create PositionSymbolResolver — watches positions, manages DXLink subscriptions

**Files:**
- Create: `src/tastytrade/subscription/resolver.py`
- Test: `unit_tests/subscription/test_position_resolver.py` (create)

**Context:** When positions change in Redis, the corresponding streamer symbols need to be subscribed on DXLink. This resolver reads the current position set from Redis, diffs against currently subscribed symbols, and calls `dxlink.subscribe()` / `dxlink.unsubscribe()`. It can run periodically or reactively.

**Step 1: Write the failing tests**

```python
# unit_tests/subscription/test_position_resolver.py
"""Tests for PositionSymbolResolver — diffs position symbols against subscriptions."""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tastytrade.subscription.resolver import PositionSymbolResolver


def make_position_json(symbol: str, streamer: str, qty: str = "1.0") -> str:
    data: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": symbol,
        "instrument-type": "Equity Option",
        "quantity": qty,
        "quantity-direction": "Long" if float(qty) > 0 else "Zero",
        "streamer-symbol": streamer,
    }
    return json.dumps(data)


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_dxlink() -> AsyncMock:
    mock = AsyncMock()
    mock.subscribe = AsyncMock()
    mock.unsubscribe = AsyncMock()
    return mock


@pytest.fixture
def resolver(mock_redis: AsyncMock, mock_dxlink: AsyncMock) -> PositionSymbolResolver:
    r = PositionSymbolResolver.__new__(PositionSymbolResolver)
    r.redis = mock_redis
    r.dxlink = mock_dxlink
    r.subscribed_symbols: set[str] = set()
    return r


@pytest.mark.asyncio
async def test_resolve_subscribes_new_symbols(resolver: PositionSymbolResolver, mock_redis: AsyncMock, mock_dxlink: AsyncMock) -> None:
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
        b".SPY260402P666": make_position_json("SPY 260402P666", ".SPY260402P666").encode(),
    }
    await resolver.resolve()
    mock_dxlink.subscribe.assert_called_once()
    subscribed = set(mock_dxlink.subscribe.call_args[0][0])
    assert subscribed == {"SPY", ".SPY260402P666"}


@pytest.mark.asyncio
async def test_resolve_unsubscribes_closed_positions(resolver: PositionSymbolResolver, mock_redis: AsyncMock, mock_dxlink: AsyncMock) -> None:
    resolver.subscribed_symbols = {"SPY", ".SPY260402P666"}
    # Only SPY remains in Redis
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
    }
    await resolver.resolve()
    mock_dxlink.unsubscribe.assert_called_once()
    unsubscribed = set(mock_dxlink.unsubscribe.call_args[0][0])
    assert unsubscribed == {".SPY260402P666"}


@pytest.mark.asyncio
async def test_resolve_no_change_no_calls(resolver: PositionSymbolResolver, mock_redis: AsyncMock, mock_dxlink: AsyncMock) -> None:
    resolver.subscribed_symbols = {"SPY"}
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
    }
    await resolver.resolve()
    mock_dxlink.subscribe.assert_not_called()
    mock_dxlink.unsubscribe.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_updates_subscribed_set(resolver: PositionSymbolResolver, mock_redis: AsyncMock, mock_dxlink: AsyncMock) -> None:
    mock_redis.hgetall.return_value = {
        b"SPY": make_position_json("SPY", "SPY").encode(),
    }
    await resolver.resolve()
    assert resolver.subscribed_symbols == {"SPY"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest unit_tests/subscription/test_position_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/tastytrade/subscription/resolver.py
"""Resolves position streamer symbols into DXLink subscriptions.

Reads current positions from Redis HSET, diffs against currently subscribed
symbols, and calls subscribe/unsubscribe on the DXLink manager.
Single responsibility: position symbols → DXLink subscriptions.
"""

import logging
import os
from typing import Optional, Protocol

import redis.asyncio as aioredis  # type: ignore

from tastytrade.accounts.publisher import AccountStreamPublisher

logger = logging.getLogger(__name__)


class SymbolSubscriber(Protocol):
    """Protocol for anything that can subscribe/unsubscribe symbols."""

    async def subscribe(self, symbols: list[str]) -> None: ...
    async def unsubscribe(self, symbols: list[str]) -> None: ...


class PositionSymbolResolver:
    """Diffs position symbols against active subscriptions."""

    def __init__(
        self,
        dxlink: SymbolSubscriber,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        self.redis = aioredis.Redis(host=host, port=port)
        self.dxlink = dxlink
        self.subscribed_symbols: set[str] = set()

    async def resolve(self) -> None:
        """Read positions from Redis, diff, subscribe/unsubscribe."""
        raw = await self.redis.hgetall(AccountStreamPublisher.POSITIONS_KEY)
        current_symbols = {key.decode("utf-8") for key in raw.keys()}

        to_subscribe = current_symbols - self.subscribed_symbols
        to_unsubscribe = self.subscribed_symbols - current_symbols

        if to_subscribe:
            await self.dxlink.subscribe(sorted(to_subscribe))
            logger.info("Subscribed %d position symbols: %s", len(to_subscribe), sorted(to_subscribe))

        if to_unsubscribe:
            await self.dxlink.unsubscribe(sorted(to_unsubscribe))
            logger.info("Unsubscribed %d closed symbols: %s", len(to_unsubscribe), sorted(to_unsubscribe))

        self.subscribed_symbols = current_symbols
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest unit_tests/subscription/test_position_resolver.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tastytrade/subscription/resolver.py unit_tests/subscription/test_position_resolver.py
git commit -m "TT-59: Add PositionSymbolResolver for position-driven DXLink subscriptions"
```

---

### Task 4: Create account-stream orchestrator with self-healing

**Files:**
- Create: `src/tastytrade/accounts/orchestrator.py`
- Modify: `src/tastytrade/subscription/cli.py` (add `account-stream` command)
- Modify: `pyproject.toml` (add CLI entry point)
- Test: `unit_tests/accounts/test_account_orchestrator.py` (create)

**Context:** This is the startup function — like `run_subscription` is for market data. It runs the AccountStreamer, publishes events to Redis via AccountStreamPublisher, and runs the PositionSymbolResolver to keep DXLink subscriptions in sync. Self-heals with the same exponential backoff pattern as `run_subscription` in `src/tastytrade/subscription/orchestrator.py:505-598`.

**Step 1: Write the failing tests**

```python
# unit_tests/accounts/test_account_orchestrator.py
"""Tests for account stream orchestrator — self-healing lifecycle."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.accounts.orchestrator import AccountStreamError, run_account_stream_once


@pytest.mark.asyncio
async def test_run_once_calls_streamer_start() -> None:
    """Verify the orchestrator starts the AccountStreamer."""
    with patch("tastytrade.accounts.orchestrator.AccountStreamer") as MockStreamer, \
         patch("tastytrade.accounts.orchestrator.AccountStreamPublisher") as MockPublisher, \
         patch("tastytrade.accounts.orchestrator.PositionSymbolResolver") as MockResolver, \
         patch("tastytrade.accounts.orchestrator.RedisConfigManager") as MockConfig, \
         patch("tastytrade.accounts.orchestrator.Credentials"):

        mock_config = MagicMock()
        mock_config.initialize = MagicMock()
        mock_config.get = MagicMock(return_value="LIVE")
        MockConfig.return_value = mock_config

        mock_streamer = AsyncMock()
        mock_streamer.start = AsyncMock()
        mock_streamer.queues = {
            __import__("tastytrade.config.enumerations", fromlist=["AccountEventType"]).AccountEventType.CURRENT_POSITION: asyncio.Queue(),
            __import__("tastytrade.config.enumerations", fromlist=["AccountEventType"]).AccountEventType.ACCOUNT_BALANCE: asyncio.Queue(),
        }
        mock_streamer.close = AsyncMock()
        MockStreamer.return_value = mock_streamer

        mock_publisher = AsyncMock()
        mock_publisher.close = AsyncMock()
        MockPublisher.return_value = mock_publisher

        mock_resolver = AsyncMock()
        MockResolver.return_value = mock_resolver

        # Cancel quickly to avoid infinite loop
        with pytest.raises(asyncio.CancelledError):
            task = asyncio.create_task(run_account_stream_once())
            await asyncio.sleep(0.05)
            task.cancel()
            await task

        mock_streamer.start.assert_awaited_once()


def test_account_stream_error_tracks_health() -> None:
    err = AccountStreamError("test", was_healthy=True)
    assert err.was_healthy is True
    err2 = AccountStreamError("test", was_healthy=False)
    assert err2.was_healthy is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest unit_tests/accounts/test_account_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/tastytrade/accounts/orchestrator.py
"""Account stream orchestrator — runs AccountStreamer and publishes to Redis.

Mirrors the self-healing pattern from subscription/orchestrator.py.
Startup function: connects AccountStreamer, publishes events to Redis,
and runs PositionSymbolResolver to keep DXLink subscriptions in sync.
"""

import asyncio
import logging
import time
from typing import Optional

from tastytrade.accounts.models import AccountBalance, Position
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.accounts.streamer import AccountStreamer
from tastytrade.config import RedisConfigManager
from tastytrade.config.enumerations import AccountEventType
from tastytrade.connections import Credentials
from tastytrade.subscription.resolver import PositionSymbolResolver

logger = logging.getLogger(__name__)

HEALTHY_CONNECTION_THRESHOLD = 60
RESOLVER_INTERVAL_SECONDS = 5


class AccountStreamError(Exception):
    """Wraps account stream failures with health context for retry logic."""

    def __init__(self, message: str, was_healthy: bool = False) -> None:
        super().__init__(message)
        self.was_healthy = was_healthy


async def _consume_positions(
    queue: asyncio.Queue,
    publisher: AccountStreamPublisher,
) -> None:
    """Drain position events from AccountStreamer queue and publish to Redis."""
    while True:
        position: Position = await queue.get()
        try:
            await publisher.publish_position(position)
        except Exception as e:
            logger.error("Failed to publish position %s: %s", position.symbol, e)
        finally:
            queue.task_done()


async def _consume_balances(
    queue: asyncio.Queue,
    publisher: AccountStreamPublisher,
) -> None:
    """Drain balance events from AccountStreamer queue and publish to Redis."""
    while True:
        balance: AccountBalance = await queue.get()
        try:
            await publisher.publish_balance(balance)
        except Exception as e:
            logger.error("Failed to publish balance: %s", e)
        finally:
            queue.task_done()


async def _run_resolver_loop(
    resolver: PositionSymbolResolver,
    interval: float = RESOLVER_INTERVAL_SECONDS,
) -> None:
    """Periodically resolve position symbols into DXLink subscriptions."""
    while True:
        try:
            await resolver.resolve()
        except Exception as e:
            logger.error("Resolver error: %s", e)
        await asyncio.sleep(interval)


async def run_account_stream_once(
    env_file: str = ".env",
    health_interval: int = 3600,
) -> None:
    """Run a single account stream session. Raises AccountStreamError on failure."""
    streamer: Optional[AccountStreamer] = None
    publisher: Optional[AccountStreamPublisher] = None
    connection_established_at: Optional[float] = None
    tasks: list[asyncio.Task] = []

    try:
        config = RedisConfigManager(env_file=env_file)
        config.initialize(force=True)

        env_setting = config.get("ENVIRONMENT", "LIVE").upper()
        env = "Live" if env_setting == "LIVE" else "Test"
        credentials = Credentials(config=config, env=env)

        # Reset singleton for fresh start
        AccountStreamer.instance = None
        streamer = AccountStreamer(credentials)
        await streamer.start()
        logger.info("AccountStreamer started")

        publisher = AccountStreamPublisher()

        # Start queue consumers
        tasks.append(asyncio.create_task(
            _consume_positions(streamer.queues[AccountEventType.CURRENT_POSITION], publisher),
            name="position_consumer",
        ))
        tasks.append(asyncio.create_task(
            _consume_balances(streamer.queues[AccountEventType.ACCOUNT_BALANCE], publisher),
            name="balance_consumer",
        ))

        connection_established_at = time.monotonic()
        logger.info("Account stream active — publishing to Redis")

        # Wait for reconnection signal or health interval
        while True:
            monitor_task = asyncio.create_task(streamer.wait_for_reconnect_signal())
            sleep_task = asyncio.create_task(asyncio.sleep(health_interval))

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
                logger.warning("Account stream reconnection triggered: %s", reason.value)
                raise ConnectionError(f"Reconnection triggered: {reason.value}")

            # Health log
            uptime = int(time.monotonic() - connection_established_at)
            logger.info("Account stream health — uptime: %ds", uptime)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        was_healthy = (
            connection_established_at is not None
            and (time.monotonic() - connection_established_at) > HEALTHY_CONNECTION_THRESHOLD
        )
        raise AccountStreamError(str(e), was_healthy=was_healthy) from e
    finally:
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if streamer is not None:
            await streamer.close()
        if publisher is not None:
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
    """Run account stream with self-healing reconnection.

    Same retry pattern as subscription/orchestrator.py:run_subscription.
    """
    if not auto_reconnect:
        await run_account_stream_once(env_file=env_file, health_interval=health_interval)
        return

    attempt = 0
    while attempt < max_reconnect_attempts:
        try:
            await run_account_stream_once(env_file=env_file, health_interval=health_interval)
            break
        except asyncio.CancelledError:
            logger.info("Account stream cancelled by user")
            raise
        except AccountStreamError as e:
            if e.was_healthy:
                logger.info("Connection was healthy before failure, resetting retry counter")
                attempt = 0
            else:
                attempt += 1
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                "Account stream failed (attempt %d/%d): %s. Reconnecting in %.1fs",
                attempt, max_reconnect_attempts, e, delay,
            )
            await asyncio.sleep(delay)
        except Exception as e:
            attempt += 1
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                "Account stream failed (attempt %d/%d): %s. Reconnecting in %.1fs",
                attempt, max_reconnect_attempts, e, delay,
            )
            await asyncio.sleep(delay)
    else:
        logger.error("Max reconnection attempts (%d) reached, giving up", max_reconnect_attempts)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest unit_tests/accounts/test_account_orchestrator.py -v`
Expected: PASS

**Step 5: Add CLI command**

Add to `src/tastytrade/subscription/cli.py` after the existing `status` command:

```python
@cli.command(name="account-stream")
@click.option(
    "--log-level",
    default="INFO",
    callback=validate_log_level,
    help="Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO",
)
@click.option(
    "--health-interval",
    default=3600,
    type=int,
    help="Seconds between health status log entries. Default: 3600",
)
def account_stream(log_level: str, health_interval: int) -> None:
    """Start the account event stream, publishing positions and balances to Redis.

    This command connects to the TastyTrade Account Streamer WebSocket,
    publishes CurrentPosition and AccountBalance events to Redis,
    and self-heals on connection failures.

    \b
    Example:
      tasty-subscription account-stream
      tasty-subscription account-stream --log-level DEBUG
    """
    log_level_int = getattr(logging, log_level)
    setup_logging(level=log_level_int, console=True, file=False)
    local_logger = logging.getLogger(__name__)

    local_logger.info("=" * 60)
    local_logger.info("TastyTrade Account Stream - Starting")
    local_logger.info("=" * 60)

    from tastytrade.accounts.orchestrator import run_account_stream

    try:
        asyncio.run(run_account_stream(health_interval=health_interval))
    except KeyboardInterrupt:
        local_logger.info("Received interrupt signal - shutting down")
    except Exception as e:
        local_logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)

    sys.exit(0)
```

Add import at top of cli.py: `import logging` (already there).

**Step 6: Add justfile recipe**

Append to `justfile`:

```just
# Run account stream (positions/balances to Redis)
account-stream log_level="INFO":
    uv run tasty-subscription account-stream \
        --log-level {{log_level}}
```

**Step 7: Commit**

```bash
git add src/tastytrade/accounts/orchestrator.py unit_tests/accounts/test_account_orchestrator.py src/tastytrade/subscription/cli.py justfile
git commit -m "TT-59: Add account-stream orchestrator with self-healing and CLI command"
```

---

### Task 5: Create position metrics reader — pure Redis consumer

**Files:**
- Create: `src/tastytrade/analytics/positions.py`
- Add CLI: modify `src/tastytrade/subscription/cli.py`
- Test: `unit_tests/analytics/test_position_reader.py` (create)

**Context:** This is the "get my position metrics" operation. Reads positions, latest quotes, and latest Greeks from Redis HSET. Joins them via MetricsTracker. Outputs a DataFrame. No API calls, no socket connections.

**Step 1: Write the failing tests**

```python
# unit_tests/analytics/test_position_reader.py
"""Tests for PositionMetricsReader — pure Redis consumer."""

import json
from typing import Any
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from tastytrade.analytics.positions import PositionMetricsReader


def make_position_json(symbol: str, streamer: str, qty: str = "100.0", direction: str = "Long", inst_type: str = "Equity") -> str:
    return json.dumps({
        "account-number": "5WT00001",
        "symbol": symbol,
        "instrument-type": inst_type,
        "quantity": qty,
        "quantity-direction": direction,
        "streamer-symbol": streamer,
    })


def make_quote_json(symbol: str, bid: float, ask: float) -> str:
    return json.dumps({
        "eventSymbol": symbol,
        "bidPrice": bid,
        "askPrice": ask,
        "bidSize": 100.0,
        "askSize": 200.0,
    })


def make_greeks_json(symbol: str, delta: float, iv: float) -> str:
    return json.dumps({
        "eventSymbol": symbol,
        "delta": delta,
        "gamma": 0.01,
        "theta": -0.05,
        "vega": 0.10,
        "rho": -0.02,
        "volatility": iv,
    })


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def reader(mock_redis: AsyncMock) -> PositionMetricsReader:
    r = PositionMetricsReader.__new__(PositionMetricsReader)
    r.redis = mock_redis
    return r


@pytest.mark.asyncio
async def test_read_returns_dataframe(reader: PositionMetricsReader, mock_redis: AsyncMock) -> None:
    mock_redis.hgetall.side_effect = [
        {b"SPY": make_position_json("SPY", "SPY").encode()},  # positions
        {b"SPY": make_quote_json("SPY", 690.0, 691.0).encode()},  # quotes
        {},  # greeks
    ]
    df = await reader.read()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["mid_price"] == 690.5


@pytest.mark.asyncio
async def test_read_joins_greeks_for_options(reader: PositionMetricsReader, mock_redis: AsyncMock) -> None:
    mock_redis.hgetall.side_effect = [
        {b".SPY260402P666": make_position_json("SPY P666", ".SPY260402P666", inst_type="Equity Option").encode()},
        {b".SPY260402P666": make_quote_json(".SPY260402P666", 5.75, 5.80).encode()},
        {b".SPY260402P666": make_greeks_json(".SPY260402P666", -0.24, 0.19).encode()},
    ]
    df = await reader.read()
    assert len(df) == 1
    assert df.iloc[0]["delta"] == -0.24
    assert df.iloc[0]["implied_volatility"] == 0.19


@pytest.mark.asyncio
async def test_read_empty_positions_returns_empty_df(reader: PositionMetricsReader, mock_redis: AsyncMock) -> None:
    mock_redis.hgetall.side_effect = [{}, {}, {}]
    df = await reader.read()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


@pytest.mark.asyncio
async def test_read_includes_required_columns(reader: PositionMetricsReader, mock_redis: AsyncMock) -> None:
    mock_redis.hgetall.side_effect = [
        {b"SPY": make_position_json("SPY", "SPY").encode()},
        {b"SPY": make_quote_json("SPY", 690.0, 691.0).encode()},
        {},
    ]
    df = await reader.read()
    for col in ["symbol", "quantity", "quantity_direction", "mid_price", "delta", "implied_volatility"]:
        assert col in df.columns, f"Missing column: {col}"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest unit_tests/analytics/test_position_reader.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/tastytrade/analytics/positions.py
"""Position metrics reader — pure Redis consumer.

Reads positions, latest quotes, and latest Greeks from Redis HSET.
Joins them via MetricsTracker into a DataFrame.
No API calls, no socket connections.
"""

import json
import logging
import os
from typing import Optional

import pandas as pd
import redis.asyncio as aioredis  # type: ignore

from tastytrade.accounts.models import Position
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.analytics.metrics import MetricsTracker
from tastytrade.messaging.models.events import GreeksEvent, QuoteEvent

logger = logging.getLogger(__name__)


class PositionMetricsReader:
    """Reads position metrics from Redis. Pure consumer — no connections."""

    QUOTES_KEY = "tastytrade:latest:QuoteEvent"
    GREEKS_KEY = "tastytrade:latest:GreeksEvent"

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        self.redis = aioredis.Redis(host=host, port=port)

    async def read(self) -> pd.DataFrame:
        """Read positions + market data from Redis, return joined DataFrame."""
        # 1. Read positions
        raw_positions = await self.redis.hgetall(AccountStreamPublisher.POSITIONS_KEY)
        if not raw_positions:
            return MetricsTracker().df

        positions = []
        for _key, value in raw_positions.items():
            try:
                positions.append(Position.model_validate(json.loads(value)))
            except Exception as e:
                logger.warning("Failed to parse position: %s", e)

        # 2. Load into tracker
        tracker = MetricsTracker()
        tracker.load_positions(positions)

        # 3. Read latest quotes
        raw_quotes = await self.redis.hgetall(self.QUOTES_KEY)
        for _key, value in raw_quotes.items():
            try:
                event = QuoteEvent.model_validate(json.loads(value))
                tracker.on_quote_event(event)
            except Exception as e:
                logger.debug("Skipped quote: %s", e)

        # 4. Read latest Greeks
        raw_greeks = await self.redis.hgetall(self.GREEKS_KEY)
        for _key, value in raw_greeks.items():
            try:
                event = GreeksEvent.model_validate(json.loads(value))
                tracker.on_greeks_event(event)
            except Exception as e:
                logger.debug("Skipped greeks: %s", e)

        return tracker.df

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest unit_tests/analytics/test_position_reader.py -v`
Expected: PASS

**Step 5: Add CLI command**

Add to `src/tastytrade/subscription/cli.py`:

```python
@cli.command(name="positions")
def positions_cmd() -> None:
    """Show current position metrics from Redis.

    Reads positions, quotes, and Greeks from Redis and displays
    a joined DataFrame. Requires account-stream and subscribe
    to be running.

    \b
    Example:
      tasty-subscription positions
    """
    import asyncio
    from tastytrade.analytics.positions import PositionMetricsReader

    async def _run() -> None:
        reader = PositionMetricsReader()
        try:
            df = await reader.read()
            if df.empty:
                click.echo("No positions found in Redis. Is account-stream running?")
                return
            display_cols = [
                "underlying_symbol", "symbol", "instrument_type",
                "quantity", "quantity_direction",
                "mid_price", "delta", "implied_volatility",
            ]
            available = [c for c in display_cols if c in df.columns]
            click.echo(df[available].to_string(index=False))
        finally:
            await reader.close()

    asyncio.run(_run())
```

**Step 6: Add justfile recipe**

Append to `justfile`:

```just
# Show current position metrics from Redis
positions:
    uv run tasty-subscription positions
```

**Step 7: Commit**

```bash
git add src/tastytrade/analytics/positions.py unit_tests/analytics/test_position_reader.py src/tastytrade/subscription/cli.py justfile
git commit -m "TT-59: Add position metrics reader and CLI command"
```

---

### Task 6: Run full test suite, verify, and update integration notebook

**Files:**
- Modify: `src/devtools/playground_metrics_tracker.ipynb` (update to demonstrate Redis-based pipeline)
- All new source and test files from Tasks 1-5

**Step 1: Run all new tests**

```bash
uv run pytest unit_tests/messaging/test_redis_event_processor.py unit_tests/accounts/test_account_publisher.py unit_tests/subscription/test_position_resolver.py unit_tests/accounts/test_account_orchestrator.py unit_tests/analytics/test_position_reader.py -v
```

Expected: All PASS

**Step 2: Run existing tests to verify no regressions**

```bash
uv run pytest unit_tests/ -v
```

Expected: All PASS (existing tests unaffected)

**Step 3: Type checking**

```bash
uv run mypy src/tastytrade/messaging/processors/redis.py src/tastytrade/accounts/publisher.py src/tastytrade/accounts/orchestrator.py src/tastytrade/subscription/resolver.py src/tastytrade/analytics/positions.py
```

Expected: No errors

**Step 4: Linting**

```bash
uv run ruff check src/tastytrade/messaging/processors/redis.py src/tastytrade/accounts/publisher.py src/tastytrade/accounts/orchestrator.py src/tastytrade/subscription/resolver.py src/tastytrade/analytics/positions.py
```

Expected: No errors

**Step 5: Update playground_metrics_tracker.ipynb**

Update `src/devtools/playground_metrics_tracker.ipynb` to add cells demonstrating the new Redis-based position metrics pipeline. The existing notebook shows the direct DXLink approach — add new cells that show the Redis consumer approach:

```python
# Cell: "Position Metrics from Redis (New Pipeline)"
# This demonstrates the pure-Redis consumer path added by TT-59.
# Prerequisites: `tasty-subscription account-stream` and `tasty-subscription run` must be running.

import asyncio
from tastytrade.analytics.positions import PositionMetricsReader

async def read_position_metrics():
    reader = PositionMetricsReader()
    try:
        df = await reader.read()
        return df
    finally:
        await reader.close()

df = await read_position_metrics()
df
```

```python
# Cell: "Verify Redis HSET keys"
import redis
r = redis.Redis(host="localhost", port=6379)
print("Positions:", r.hlen("tastytrade:positions"))
print("Balances:", r.hlen("tastytrade:balances"))
print("Latest Quotes:", r.hlen("tastytrade:latest:QuoteEvent"))
print("Latest Greeks:", r.hlen("tastytrade:latest:GreeksEvent"))
```

```python
# Cell: "Display position metrics table"
display_cols = [
    "underlying_symbol", "symbol", "instrument_type",
    "quantity", "quantity_direction",
    "mid_price", "delta", "implied_volatility",
]
available = [c for c in display_cols if c in df.columns]
df[available]
```

**Step 6: Commit final state**

```bash
git add -A
git commit -m "TT-59: All tests pass, update integration notebook with Redis pipeline demo"
```
