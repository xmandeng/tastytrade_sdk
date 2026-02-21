# Signal Detection Architecture

This document describes the real-time signal detection pipeline and the
Redis-as-bus service boundary design.

---

## Overview

The signal detection system has one engine (`HullMacdEngine`) and a
three-layer architecture: CLI → EngineRunner → Engine.

Every service is a self-contained unit: Redis in → process → Redis out.
Events fire directly into the engine — no queues, no polling.

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
     EngineRunner (production)         Notebook / Direct
              │                               │
     RedisSubscription                 RedisSubscription.queue
     on_update callback                       │
              │                        engine.on_candle_event()
     engine.on_candle_event()                 │
       (direct, no queue)              engine.signals  ← read list
              │
     publisher.publish(signal)
              │
     Redis pub/sub: market:TradeSignal:hull_macd:SPX{=5m}
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
    publisher=publisher,
    channels=[f"market:CandleEvent:{sym}{{={interval}}}"],
    event_type=CandleEvent,
    on_event=engine.on_candle_event,
)
await runner.start()
```

**Data flow:**

1. DXLink (separate process) → Redis pub/sub → `RedisSubscription.listener()`
2. Typed deserialization to `CandleEvent`
3. `on_update` callback fires directly into `engine.on_candle_event()`
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

while True:
    event = await queue.get()
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
