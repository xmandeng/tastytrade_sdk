# Architecture Overview

Start here. This document describes the current-state architecture of the tastytrade SDK — what the system does, how the pieces connect, and the design patterns that hold it together.

For service-level operational details, see [streaming_services.md](streaming_services.md). For signal detection specifics, see [signal_architecture.md](signal_architecture.md).

---

## System Topology

The system is a collection of independent services that coordinate through Redis. Each service is a self-contained unit: data in → process → data out.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           TastyTrade Platform APIs                              │
│                                                                                 │
│   Account Streamer WS          DXLink WS            REST API                   │
│   (positions, balances,        (quotes, trades,      (instruments,              │
│    orders)                      Greeks, candles)       options chains)           │
└───────┬─────────────────────────────┬──────────────────────┬────────────────────┘
        │                             │                      │
        ▼                             ▼                      │
┌───────────────────┐   ┌────────────────────────┐           │
│  account-stream   │   │      subscribe         │           │
│                   │   │                        │           │
│  AccountStreamer   │   │  DXLinkManager         │           │
│       │           │   │       │                │           │
│       ▼           │   │       ▼                │           │
│  AccountStream    │   │  RedisEventProcessor   │           │
│  Publisher        │   │       │                │           │
│   │    │    │     │   │       ▼                │           │
│   ▼    ▼    ▼     │   │  Redis HSET + pub/sub  │           │
│  pos  bal  orders │   │  (quotes, Greeks)      │           │
│                   │   │                        │           │
│  InstrumentsClient├───┼────────────────────────┼───────────┘
│  (enrichment)     │   │  PositionSymbolResolver│
│                   │   │  (event-driven sub mgmt│
└───────┬───────────┘   └────────────┬───────────┘
        │                            │
        ▼                            ▼
┌─────────────────────────────────────────────────────────────┐
│                          Redis                               │
│                                                              │
│  HSET: positions, balances, quotes, Greeks, instruments      │
│  HSET: account_connection, connection (health)               │
│  pub/sub: position events, market events, failure triggers   │
└────────┬───────────────────────────────────┬────────────────┘
         │                                   │
         ▼                                   ▼
┌──────────────────┐            ┌──────────────────────────┐
│   positions      │            │   signal detection       │
│                  │            │                          │
│  PositionMetrics │            │  EngineRunner            │
│  Reader          │            │       │                  │
│       │          │            │       ▼                  │
│       ▼          │            │  HullMacdEngine          │
│  StrategyClassi- │            │       │                  │
│  fier            │            │       ▼                  │
│       │          │            │  RedisPublisher          │
│       ▼          │            │  (TradeSignal → Redis)   │
│  Terminal table  │            └──────────┬───────────────┘
└──────────────────┘                       │
                                           ▼
                              ┌──────────────────────────┐
                              │   signal persistence     │
                              │                          │
                              │  TradeSignalFeed         │
                              │  (EngineRunner as sink)  │
                              │       │                  │
                              │       ▼                  │
                              │  InfluxDB                │
                              └──────────────────────────┘
```

### Services

| Service | CLI | Purpose |
|---------|-----|---------|
| **account-stream** | `just account-stream` | Stream account events (positions, balances, orders) to Redis |
| **subscribe** | `just subscribe` | Stream market data (quotes, Greeks, candles) to Redis |
| **positions** | `just positions` | Join positions + market data from Redis into a table |
| **strategies** | `just strategies` | Classify positions into named strategies with health monitoring |
| **signal detection** | `tasty-signal run` | Detect trade signals from candle data, publish to Redis |
| **signal persistence** | `tasty-signal persist` | Persist signals from Redis to InfluxDB |
| **backtest** | `tasty-backtest` | Replay historical data through signal engines |

---

## Key Design Patterns

### 1. ReconnectSignal — Decoupled Connection Lifecycle

Both streaming services use a shared `ReconnectSignal` object for connection lifecycle management. The signal is created by the orchestrator, injected into the connection pipeline, and outlives individual connection cycles.

```
Orchestrator creates ReconnectSignal
    │
    ├── passes to Streamer (socket_listener, send_keepalives)
    ├── passes to failure_trigger_listener (Redis pub/sub simulation)
    │
    └── awaits signal.wait()
            │
            ▼
        ConnectionError → self-healing retry loop
```

**Why:** The streamer is torn down and recreated on each reconnect cycle, but the signal persists. External producers (failure simulation) and internal producers (socket errors, keepalive failures) all flow through the same object. The orchestrator has a single thing to monitor.

**Files:**
- `src/tastytrade/connections/signals.py` — `ReconnectSignal` with `.trigger(reason)`, `.wait()`, `.reset()`
- `src/tastytrade/accounts/orchestrator.py` — Account stream usage
- `src/tastytrade/subscription/orchestrator.py` — Subscription usage

### 2. Redis-as-Bus — Service Boundary Communication

Services communicate exclusively through Redis. No callbacks, no shared memory, no direct function calls across service boundaries.

```
Service A → Redis.publish(event) → Service B.subscribe(pattern)
```

Each service is a black box: Redis in → process → output. The producer doesn't know (or care) who consumes its events.

**Why:** Supports distributed deployment — each service can run in a separate container. Redis pub/sub provides the event bus; Redis HSET provides the state store. Pattern matching (`PSUBSCRIBE`) enables flexible consumer routing.

**Channel conventions:**
- `market:{EventType}:{Symbol}` — Market data events
- `market:TradeSignal:{engine}:{Symbol}` — Engine-specific signals
- `tastytrade:events:CurrentPosition` — Position change events
- `account:simulate_failure` / `subscription:simulate_failure` — Failure simulation

### 3. Protocol-Based Design — Structural Subtyping

Interfaces are defined as Python `Protocol` classes. Any class with matching method signatures satisfies the protocol — no inheritance required.

| Protocol | Location | Method | Implementations |
|----------|----------|--------|-----------------|
| `EventPublisher` | `messaging/publisher.py` | `publish(event)` | `RedisPublisher` |
| `SignalEngine` | `analytics/engines/protocol.py` | `on_candle_event(event)` | `HullMacdEngine` |
| `AuthStrategy` | `connections/auth.py` | `authenticate(session)` | `OAuth2AuthStrategy`, `LegacyAuthStrategy` |
| `SubscriptionStore` | `connections/subscription.py` | `get/set/remove` | `InMemorySubscriptionStore`, Redis-backed |

**Why:** Protocols enable dependency injection without inheritance hierarchies. New implementations can be added without modifying existing code. Testing uses mock objects that match the protocol shape.

### 4. Self-Healing Orchestrators — Exponential Backoff

Both streaming services wrap their connection logic in a retry loop with exponential backoff. The pattern is identical across services:

```python
while attempt < max_attempts:
    try:
        await run_once()          # Single connection session
        break                     # Clean exit
    except CancelledError:
        raise                     # User interrupt — never retry
    except StreamError as e:
        if e.was_healthy:
            attempt = 0           # Reset counter — was working fine
        else:
            attempt += 1          # Increment — startup failure
        delay = min(base * 2**attempt, max_delay)
        await sleep(delay)
```

**Why:** WebSocket connections fail for many reasons (auth expiry, network blips, server maintenance). The `was_healthy` flag distinguishes between "worked for hours then dropped" (reset counter, reconnect immediately) and "failed on startup" (increment counter, back off). This prevents infinite rapid retries on configuration errors while being aggressive about recovering from transient failures.

### 5. Event-Driven Position Resolution

The subscription service discovers which symbols to stream by listening to position changes — not by polling.

```
account-stream publishes position change to Redis pub/sub
    │
    ▼
PositionSymbolResolver.listener() receives event
    │
    ├── New position → subscribe symbol on DXLink
    └── Closed position (qty=0) → unsubscribe symbol
```

**Why:** Polling introduces latency and wasted cycles. The pub/sub listener reacts to changes in real time. When a new position is opened on the TastyTrade platform, the market data subscription updates within milliseconds.

### 6. Layered Configuration Resolution

Configuration values resolve through a three-layer precedence chain:

```
os.environ  →  Redis (.env file)  →  Code defaults
   (1)              (2)                  (3)
```

**Why:** The application runs in two environments with different networking (Docker container vs host machine). The `.env` file is shared between both via volume mount, so service hostnames can't go there. `os.environ` (set by Docker Compose) handles infrastructure differences; code defaults use host-friendly values (`localhost`).

See [SERVICE_DISCOVERY.md](SERVICE_DISCOVERY.md) for full details.

---

## Component Map

### Connection Layer

| File | Component | Purpose |
|------|-----------|---------|
| `connections/sockets.py` | `DXLinkManager` | DXLink WebSocket singleton for market data |
| `connections/signals.py` | `ReconnectSignal` | Shared reconnection signaling (trigger/wait/reset) |
| `connections/auth.py` | `OAuth2AuthStrategy` | TastyTrade OAuth2 authentication |
| `connections/requests.py` | `AsyncSessionHandler` | HTTP client wrapper with auth |
| `connections/routing.py` | `MessageRouter` | DXLink protocol message routing |
| `connections/subscription.py` | `SubscriptionStore` | Track active data subscriptions |

### Account Streaming

| File | Component | Purpose |
|------|-----------|---------|
| `accounts/streamer.py` | `AccountStreamer` | Account event WebSocket singleton |
| `accounts/orchestrator.py` | `run_account_stream` | Self-healing lifecycle with consumers |
| `accounts/publisher.py` | `AccountStreamPublisher` | Publish to Redis HSET + pub/sub |
| `accounts/models.py` | `Position`, `AccountBalance` | Account data models |
| `accounts/client.py` | `AccountsClient` | REST API for account operations |

### Market Data Subscription

| File | Component | Purpose |
|------|-----------|---------|
| `subscription/orchestrator.py` | `run_subscription` | Self-healing market data lifecycle |
| `subscription/resolver.py` | `PositionSymbolResolver` | Event-driven symbol subscription |
| `subscription/status.py` | Status queries | Format subscription state for display |
| `subscription/cli.py` | CLI entry points | All `tasty-subscription` commands |

### Messaging Pipeline

| File | Component | Purpose |
|------|-----------|---------|
| `messaging/handlers.py` | `EventHandler` | Route WebSocket messages to processors |
| `messaging/publisher.py` | `EventPublisher` | Protocol for event publishing |
| `messaging/models/events.py` | `BaseEvent`, `QuoteEvent`, etc. | Typed event models |
| `messaging/processors/redis.py` | `RedisEventProcessor` | Redis HSET + pub/sub writer |
| `messaging/processors/influxdb.py` | `TelegrafHTTPEventProcessor` | InfluxDB batch writer |

### Analytics

| File | Component | Purpose |
|------|-----------|---------|
| `analytics/positions.py` | `PositionMetricsReader` | Join positions + quotes + Greeks |
| `analytics/metrics.py` | `MetricsTracker` | Per-position metrics computation |
| `analytics/engines/hull_macd.py` | `HullMacdEngine` | Hull MA + MACD confluence detection |
| `analytics/engines/protocol.py` | `SignalEngine` | Protocol for signal engines |
| `analytics/strategies/classifier.py` | `StrategyClassifier` | Greedy pattern matching |
| `analytics/strategies/health.py` | `StrategyHealthMonitor` | DTE/delta drift warnings |

### Signal Service

| File | Component | Purpose |
|------|-----------|---------|
| `signal/runner.py` | `EngineRunner` | Generic harness: subscription → engine → publisher |
| `signal/cli.py` | CLI entry points | `tasty-signal run`, `tasty-signal persist` |

### Backtesting

| File | Component | Purpose |
|------|-----------|---------|
| `backtest/runner.py` | `BacktestRunner` | Multi-timeframe historical replay |
| `backtest/replay.py` | Historical replay | InfluxDB → Redis replay |
| `backtest/publisher.py` | `BacktestPublisher` | Enrich signals with pricing data |

### Configuration

| File | Component | Purpose |
|------|-----------|---------|
| `config/manager.py` | `RedisConfigManager` | Three-layer config resolution |
| `config/enumerations.py` | Enums | `AccountEventType`, `ReconnectReason`, `Channels` |
| `config/configurations.py` | Channel specs | DXLink channel configuration |

### Observability

| File | Component | Purpose |
|------|-----------|---------|
| `common/observability.py` | OpenTelemetry setup | Grafana Cloud tracing |
| `common/logging.py` | Structured logging | Loguru-based logging (PII-free) |

---

## Related Documentation

| Document | Covers |
|----------|--------|
| [streaming_services.md](streaming_services.md) | Operational guide for account-stream and subscribe services |
| [signal_architecture.md](signal_architecture.md) | Signal detection pipeline, EngineRunner, TradeSignalFeed |
| [SERVICE_DISCOVERY.md](SERVICE_DISCOVERY.md) | Layered configuration resolution across environments |
| [CHANGELOG.md](../CHANGELOG.md) | Sprint-by-sprint record of changes |
| [docs/plans/](plans/) | Per-ticket implementation plans |
| [docs/architecture-map/](architecture-map/) | Interactive visual architecture explorer |
