# Signal Detection Architecture

This document describes the real-time signal detection pipeline, signal
persistence, and the Redis-as-bus service boundary design.

---

## Overview

The signal system uses `EngineRunner` as a reusable integration block —
same harness, different callback:

- **Signal Detection:** `EngineRunner(on_event=engine.on_candle_event)`
- **TradeSignalFeed:** `EngineRunner(on_event=processor.process_event)`

These are independent services. The TradeSignalFeed subscribes to Redis
directly — it has no knowledge of the detection pipeline. Each service
is a self-contained unit: Redis in → process → output. Events fire
directly into the callback — no queues, no polling.

```
                  ┌─────────────────────────────────────────────────┐
                  │         DXLink (separate process)               │
                  │  Streams live market data via WebSocket          │
                  └───────────┬─────────────────────────────────────┘
                              │
                    Redis pub/sub publish
                    channel: market:CandleEvent:SPX{=5m}
                              │
              ┌───────────────┴───────────────┐
              │                               │
     EngineRunner (detection)          Notebook / Direct
              │                               │
     RedisSubscription                 RedisSubscription.queue
     on_event callback                        │
              │                        engine.on_candle_event()
     engine.on_candle_event()                 │
       (direct, no queue)              engine.signals  ← read list
              │
     publisher.publish(signal)
              │
     Redis pub/sub: market:TradeSignal:hull_macd:SPX{=5m}
              │
     EngineRunner (TradeSignalFeed)
              │
     RedisSubscription
     on_event callback
              │
     processor.process_event(signal)
       (direct, no queue)
              │
     InfluxDB batch write
```

---

## Three-Layer Architecture

```
cli.py    → What to run (factory: pick engine, channels, event type)
runner.py → How to run (generic harness: wire subscription, manage lifecycle)
engine    → The work (pure state machine: event in, signal out)
```

Each layer knows nothing about the one above it.

## EngineRunner (Production)

Used by: `tasty-signal run --symbols SPX --intervals 5m`

```python
# cli.py — factory
subscription = RedisSubscription(config)
publisher = RedisPublisher()
engine = HullMacdEngine(publisher=publisher)

runner = EngineRunner(
    name=engine.name,
    subscription=subscription,
    channels=[f"market:CandleEvent:{sym}{{={interval}}}"],
    event_type=CandleEvent,
    on_event=engine.on_candle_event,
    publisher=publisher,
)
await runner.start()
```

**Data flow:**

1. DXLink (separate process) → Redis pub/sub → `RedisSubscription.listener()`
2. Typed deserialization to `CandleEvent`
3. `on_event` callback fires directly into `engine.on_candle_event()`
4. Engine detects confluence → `publisher.publish(signal)` → Redis
5. Signal appears on `market:TradeSignal:hull_macd:SPX{=5m}`

No queues. No polling. The Redis async listener IS the event loop.

**When to use:** Automated production pipelines where signals must be
distributed to downstream consumers.

---

## Notebook / Direct Consumption (Development)

Used by: `playground_signals.ipynb`, ad-hoc analysis, backtesting

```python
engine = HullMacdEngine()
engine.set_prior_close("SPX{=5m}", prior_close)

await subscription.subscribe("market:CandleEvent:SPX{=5m}")
queue = subscription.queue["CandleEvent:SPX{=5m}"]

max_candles = 500  # bounded — declare termination upfront
for _ in range(max_candles):
    event = await asyncio.wait_for(queue.get(), timeout=60.0)
    engine.on_candle_event(event)

    if engine.signals:
        latest = engine.signals[-1]  # read directly from list
```

**When to use:** Development, testing, real-time monitoring, manual
exploration during market hours.

The engine is a **standalone state machine** — it accepts `CandleEvent`
in, accumulates internal state, and appends `TradeSignal` to a list.
No framework required.

---

## TradeSignalFeed (Independent Service)

Used by: `tasty-signal persist --channels "market:TradeSignal:*"`

An independent service that subscribes to `market:TradeSignal:*` on Redis
and writes every signal to InfluxDB. Has no knowledge of who produced
the signals or why — it processes all TradeSignal events regardless of
source engine. Could run on a completely different host from signal
detection.

```python
subscription = RedisSubscription(config)
processor = TelegrafHTTPEventProcessor()

runner = EngineRunner(
    name="trade_signal_feed",
    subscription=subscription,
    channels=["market:TradeSignal:*"],
    event_type=TradeSignal,
    on_event=processor.process_event,
    # no publisher — InfluxDB sink
)
await runner.start()
```

**Data flow:**

1. Redis `PSUBSCRIBE market:TradeSignal:*` → `RedisSubscription.listener()`
2. Typed deserialization to `TradeSignal`
3. `on_event` callback fires directly into `processor.process_event()`
4. `TelegrafHTTPEventProcessor` writes to InfluxDB (batch)

Uses EngineRunner as a harness (same as detection) but with:

- `on_event = processor.process_event` (not `engine.on_candle_event`)
- No publisher — pure sink, not a relay
- `publisher` is optional (`RedisPublisher | None = None`)

**When to use:** Automated persistence of signals to InfluxDB for
historical analysis, charting, and backtesting.

---

## Service Boundary Principle

This system is designed for **distributed deployment**: multiple containers,
each subscribing to Redis for input and publishing to Redis for output.
**Redis IS the bus.** Each service is a self-contained unit:
Redis in → process → Redis out.

### Why callbacks are wrong at service boundaries

The previous pattern wired services together with callbacks:

```python
# ANTI-PATTERN — do not use
engine.on_signal = publisher.publish  # orchestrator reaches across services
```

This creates invisible coupling — the orchestrator must know about both the
engine and the publisher, violating localized proximity. It also breaks
distributed deployment: callbacks are in-process function calls, not
network-addressable messages.

### EventPublisher protocol

Each engine owns its own publisher. Signal emission is a local concern:

```python
# Correct — engine owns its own I/O
engine = HullMacdEngine(publisher=RedisPublisher())
```

The `EventPublisher` protocol (`messaging/publisher.py`) defines the
structural interface:

```python
class EventPublisher(Protocol):
    def publish(self, event: BaseEvent) -> None: ...
```

`RedisPublisher` satisfies this protocol. Any class with a matching
`publish` method works — no inheritance required.

### Engine-aware channel naming

Events with an `engine` attribute get engine-specific channels:

```
market:TradeSignal:hull_macd:SPX{=5m}    ← engine-specific
market:TradeSignal:rsi:SPX{=5m}          ← future engine
market:CandleEvent:SPX{=5m}             ← no engine field, unchanged
```

Consumers use Redis `PSUBSCRIBE` pattern matching (server-side filtering):

- `market:TradeSignal:hull_macd:*` — only HullMACD signals
- `market:TradeSignal:*:SPX{=5m}` — all engines for SPX 5m
- `market:TradeSignal:*` — everything

### Distributed topology

```
Container A: RedisSubscription → HullMacdEngine → RedisPublisher
                 ↑ (CandleEvent)                      ↓ (TradeSignal:hull_macd)
                 └──────────────── Redis ──────────────────┘

Container B: RedisSubscription → RSIEngine → RedisPublisher
                 ↑ (CandleEvent)                  ↓ (TradeSignal:rsi)
                 └──────────────── Redis ──────────────┘

Container C: RedisSubscription → AlertService → RedisPublisher
                 ↑ (TradeSignal:hull_macd)            ↓ (AlertEvent)
                 └──────────────── Redis ──────────────┘
```

---

## Key Components

### HullMacdEngine

Location: `src/tastytrade/analytics/engines/hull_macd.py`

Standalone state machine. No external dependencies at runtime beyond
the `hull()` and `macd()` indicator functions.

- **Input:** `CandleEvent` via `on_candle_event()`
- **Output:** `TradeSignal` appended to `self.signals`
- **State:** Per-symbol `TimeframeState` tracking hull direction, MACD
  position, armed indicators, and open positions
- **Time gates:** `earliest_entry` (default 10:00 ET) and `latest_entry`
  (default 15:00 ET)

### RedisSubscription

Location: `src/tastytrade/providers/subscriptions.py`

Async Redis pub/sub consumer. Deserializes messages back into typed
`BaseEvent` objects and routes to per-symbol `asyncio.Queue` instances.

- Subscribe: `await subscription.subscribe("market:CandleEvent:SPX{=5m}")`
- Consume: `event = await subscription.queue["CandleEvent:SPX{=5m}"].get()`
- Each `.get()` returns a fully typed `CandleEvent` ready for the engine

### TradeSignal

Location: `src/tastytrade/analytics/engines/models.py`

Extends `BaseAnnotation` so it can be persisted to InfluxDB and rendered
on charts. Key fields:

| Field | Description |
|---|---|
| `signal_type` | `OPEN` or `CLOSE` |
| `direction` | `BULLISH` or `BEARISH` |
| `trigger` | `hull`, `macd`, or `confluence` |
| `close_price` | Candle close at trigger time (entry spot price) |
| `hull_value` | HMA value at signal time |
| `macd_value` | MACD line value |
| `macd_signal` | MACD signal line value |
| `macd_histogram` | MACD histogram value |

---

## Design Maxims

### No unbounded loops

`while True` is forbidden. Every loop must declare its termination
condition upfront — the reason for running and the reason for stopping
should both be evident at the outset.

```python
# ANTI-PATTERN — no declared intent, no exit condition
while True:
    event = await queue.get()
    process(event)

# CORRECT — bounded by count
for _ in range(max_events):
    event = await asyncio.wait_for(queue.get(), timeout=60.0)
    process(event)

# CORRECT — bounded by async signal (EngineRunner pattern)
await asyncio.Event().wait()  # explicit: "wait until cancelled"
```

Production services use `asyncio.Event().wait()` — a clear declaration
that the process runs until externally cancelled. Notebooks and scripts
use bounded loops (`for _ in range(n)`) with timeouts.

### Event flow over callbacks

The system is compartmentalized along event boundaries. Each service
subscribes to its input events and publishes its output events. The
event flow through Redis is the architecture — not function calls
between objects.

Callbacks are a lesser pattern — they create direct coupling between
caller and callee, making them suitable only for in-process wiring
within a single service (e.g., `on_event` inside EngineRunner). They
must never cross service boundaries.

```
CORRECT — event flow through Redis:
  ServiceA → Redis.publish(event) → ServiceB.subscribe(pattern)

ANTI-PATTERN — callback across services:
  ServiceA.on_signal = ServiceB.process  # invisible coupling
```

Each service is a black box: Redis in → process → output. The producer
doesn't know (or care) who consumes its events.

---

## Future: Spot Price and Options Chain

When a signal fires, `close_price` captures the triggering candle's close.
For more precise entry pricing:

1. **Mid price from live Quote feed:** Subscribe to `market:QuoteEvent:SPX`
   alongside the candle feed. At signal time, read the latest quote from
   its queue to get bid/ask mid as the spot price.

2. **Options chain at ATM +/-5:** At signal time, query the TastyTrade
   options chain API for strikes at ATM, ATM+5, ATM-5. This is an API
   call that adds latency — acceptable for 0DTE decision-making but
   should not block signal detection.

Both are additive — the engine fires the signal, then enrichment
happens after.
