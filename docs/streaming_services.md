# Streaming Services

Two independent services stream account and market data into Redis. A third command reads the joined result.

```
┌─────────────────────┐     ┌─────────────────────┐
│   account-stream    │     │     subscribe        │
│                     │     │                      │
│  AccountStreamer WS  │     │  DXLink WS           │
│         │           │     │       │              │
│         ▼           │     │       ▼              │
│  AccountStream      │     │  RedisEventProcessor │
│  Publisher          │     │       │              │
│    │         │      │     │       ▼              │
│    ▼         ▼      │     │  Redis HSET          │
│  HSET     pub/sub ──────────► PositionSymbol     │
│ positions  events   │     │  Resolver            │
│ balances            │     │    │                 │
└─────────────────────┘     │    ▼                 │
                            │  subscribe/unsub     │
                            │  on DXLink           │
                            └─────────────────────-┘

┌──────────────────────────────────────────────────┐
│                    Redis                         │
│                                                  │
│  tastytrade:positions        (HSET — positions)  │
│  tastytrade:balances         (HSET — balances)   │
│  tastytrade:latest:QuoteEvent  (HSET — quotes)   │
│  tastytrade:latest:GreeksEvent (HSET — Greeks)   │
│  tastytrade:events:CurrentPosition (pub/sub)     │
└──────────────────────────────────────────────────┘
```

---

## Running the Services

Start each service in its own terminal. Order matters — start `account-stream` first so positions are in Redis when the subscription resolver does its initial sync.

### Terminal 1: Account Stream

```bash
just account-stream
```

Connects to the TastyTrade Account Streamer WebSocket. Publishes `CurrentPosition` and `AccountBalance` events to Redis HSET. Self-heals with exponential backoff on connection failures.

### Terminal 2: Market Data Subscription

```bash
just subscribe
```

Opens a DXLink WebSocket for market data (Quote, Trade, Greeks, Candle). On startup, the **position resolver** reads all positions from Redis and subscribes their streamer symbols on DXLink. After that, it listens to the `tastytrade:events:CurrentPosition` pub/sub channel and reacts to position changes in real time — no polling.

### Reading Position Metrics

Once both services are running:

```bash
just positions
```

Joins positions + quotes + Greeks from Redis into a single table, sorted by underlying symbol. No API calls or socket connections — pure Redis reads.

---

## How the Services Connect

The two services are **independent processes** that coordinate through Redis:

1. `account-stream` writes positions to `tastytrade:positions` HSET and publishes each change to `tastytrade:events:CurrentPosition`
2. `subscribe` runs a position resolver that listens to that pub/sub channel
3. When a new position appears, the resolver subscribes its streamer symbol on DXLink
4. When a position closes (quantity = 0), the resolver unsubscribes
5. DXLink market data flows through `RedisEventProcessor` into `tastytrade:latest:QuoteEvent` and `tastytrade:latest:GreeksEvent` HSETs
6. `just positions` reads all three HSETs and joins them

---

## Service Details

### account-stream

| | |
|---|---|
| **CLI** | `tasty-subscription account-stream` |
| **Recipe** | `just account-stream` |
| **Source** | `src/tastytrade/accounts/orchestrator.py` |
| **WebSocket** | TastyTrade Account Streamer (singleton) |
| **Redis writes** | `tastytrade:positions` (HSET), `tastytrade:balances` (HSET) |
| **Redis pub/sub** | `tastytrade:events:CurrentPosition` (on every position change) |
| **Self-healing** | Exponential backoff, resets on healthy connection |

### subscribe

| | |
|---|---|
| **CLI** | `tasty-subscription run --symbols ... --intervals ... --start-date ...` |
| **Recipe** | `just subscribe` |
| **Source** | `src/tastytrade/subscription/orchestrator.py` |
| **WebSocket** | DXLink (Quote, Trade, Greeks, Candle) |
| **Redis writes** | `tastytrade:latest:QuoteEvent` (HSET), `tastytrade:latest:GreeksEvent` (HSET), plus pub/sub per event |
| **Position resolver** | `src/tastytrade/subscription/resolver.py` — event-driven via Redis pub/sub |
| **Self-healing** | Exponential backoff, candle backfill on reconnect |

### positions

| | |
|---|---|
| **CLI** | `tasty-subscription positions` |
| **Recipe** | `just positions` |
| **Source** | `src/tastytrade/analytics/positions.py` |
| **Redis reads** | Joins `tastytrade:positions` + `tastytrade:latest:QuoteEvent` + `tastytrade:latest:GreeksEvent` |
| **Output** | Table sorted by underlying_symbol, symbol |

---

## Redis Keys Reference

| Key | Type | Written by | Contents |
|-----|------|-----------|----------|
| `tastytrade:positions` | HSET | account-stream | Position JSON keyed by streamer symbol |
| `tastytrade:balances` | HSET | account-stream | Balance JSON keyed by account |
| `tastytrade:latest:QuoteEvent` | HSET | subscribe | Latest quote per symbol |
| `tastytrade:latest:GreeksEvent` | HSET | subscribe | Latest Greeks per symbol |
| `tastytrade:events:CurrentPosition` | pub/sub | account-stream | Position change events (consumed by resolver) |
| `market:{EventType}:{Symbol}` | pub/sub | subscribe | Real-time market data events |

---

## Shutdown

Each service shuts down cleanly on `Ctrl+C`:

- Cancels background tasks (resolver, failure listener, consumers)
- Marks subscriptions inactive in Redis
- Flushes buffered writes (InfluxDB processors)
- Closes WebSocket connections

---

## Notebook

The metrics tracker notebook at `src/devtools/playground_metrics_tracker.ipynb` provides an interactive view of the pipeline output. Section 7 demonstrates the Redis-backed position metrics reader — it works as long as both services are running.

---

## Files

| File | Role |
|------|------|
| `src/tastytrade/accounts/orchestrator.py` | Account stream lifecycle with self-healing |
| `src/tastytrade/accounts/publisher.py` | Publishes positions/balances to Redis |
| `src/tastytrade/accounts/streamer.py` | Account Streamer WebSocket client |
| `src/tastytrade/subscription/orchestrator.py` | Market data subscription lifecycle |
| `src/tastytrade/subscription/resolver.py` | Event-driven position → DXLink subscription |
| `src/tastytrade/messaging/processors/redis.py` | Writes market data to Redis HSET + pub/sub |
| `src/tastytrade/analytics/positions.py` | Joins position + quote + Greeks from Redis |
| `src/tastytrade/subscription/cli.py` | CLI entry points for all commands |
