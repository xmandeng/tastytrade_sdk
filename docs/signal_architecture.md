# Signal Detection Architecture

This document describes the real-time signal detection pipeline, its two
consumption paths, and the design rationale behind each.

---

## Overview

The signal detection system has one engine (`HullMacdEngine`) and **two
independent consumption paths**. Both receive the same `CandleEvent`
objects; they differ in where those events come from and how signals are
collected.

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
     PATH A: Production               PATH B: Notebook / Direct
     (EventHandler pipeline)           (Redis → Engine)
              │                               │
     EventHandler.processors           RedisSubscription.queue
     ├─ TelegrafHTTPProcessor                 │
     ├─ RedisEventProcessor            await queue.get()
     └─ SignalEventProcessor                  │
              │                        engine.on_candle_event(event)
     engine.on_candle_event()                 │
              │                        engine.signals  ← read list
     on_signal callback                       │
              │                        (no callbacks needed)
     emit → re-inject into
     EventHandler chain
```

---

## Path A: Production EventHandler Pipeline

Used by: `api/main.py`, `subscription/orchestrator.py`, `scripts/dxlink_startup.py`

```python
candle_handler = dxlink.router.handler[Channels.Candle]
candle_handler.add_processor(SignalEventProcessor(engine, emit=handler.process_event))
```

**Data flow:**

1. `DXLink WebSocket` → `asyncio.Queue` → `EventHandler.queue_listener()`
2. `EventHandler.handle_message()` parses raw data into `CandleEvent`
3. Loops through `self.processors`, calling `processor.process_event(event)`
4. `SignalEventProcessor.process_event()` → `engine.on_candle_event()`
5. Engine detects confluence → calls `on_signal` callback
6. Callback fires `emit()` → re-injects `TradeSignal` into the handler chain
7. Other processors (Telegraf, Redis) write the `TradeSignal` to InfluxDB / Redis

**When to use:** Automated production pipelines where signals must be
persisted and distributed without human interaction.

**Requires:** Direct DXLink WebSocket connection in the same process.

---

## Path B: Notebook / Direct Consumption (Preferred for Development)

Used by: `playground_signals.ipynb`, ad-hoc analysis, backtesting

```python
engine = HullMacdEngine()
engine.set_prior_close("SPX{=5m}", prior_close)

await subscription.subscribe("market:CandleEvent:SPX{=5m}")
queue = subscription.queue["CandleEvent:SPX{=5m}"]

while True:
    event = await queue.get()        # async, non-blocking to event loop
    engine.on_candle_event(event)    # state machine processes candle

    if engine.signals:
        latest = engine.signals[-1]  # read directly from list
```

**Data flow:**

1. DXLink (separate process) → Redis pub/sub → `RedisSubscription.listener()`
2. `convert_message_to_event()` deserializes to `CandleEvent`
3. Event placed in `asyncio.Queue` keyed by `CandleEvent:SPX{=5m}`
4. Notebook calls `await queue.get()` — blocks until next candle arrives
5. Feeds `CandleEvent` directly to `engine.on_candle_event()`
6. Reads `engine.signals` list — no callbacks, no processor chain

**When to use:** Development, testing, real-time monitoring, manual
exploration during market hours.

**Requires:** DXLink running in a separate process with Redis pub/sub
active (the standard `tasty-subscription` setup from TT-31).

---

## Why Two Paths Exist

| Concern | Path A (Production) | Path B (Notebook) |
|---|---|---|
| DXLink location | Same process | Separate process |
| Event source | WebSocket → Queue → EventHandler | Redis pub/sub → asyncio.Queue |
| Signal delivery | Callback → emit into handler chain | Poll `engine.signals` list |
| Persistence | Automatic (Telegraf processor) | Manual or not needed |
| Wiring complexity | Processor registration, callbacks | Zero — direct function calls |
| Latency | Lowest (in-process) | Near-zero (Redis pub/sub hop) |

Path B is simpler because it decouples the engine from the processor
framework. The engine is a **standalone state machine** — it accepts
`CandleEvent` in, accumulates internal state, and appends `TradeSignal`
to a list. No framework required.

---

## Callback Analysis

The engine has an `on_signal` callback mechanism:

```python
# In HullMacdEngine._emit_signal():
self._signals.append(signal)     # Always happens — signals accumulate
if self._on_signal:
    self._on_signal(signal)      # Only fires if callback is set
```

**For Path A (Production):** The callback is how `SignalEventProcessor`
re-injects signals into the EventHandler chain for downstream persistence.

**For Path B (Notebook):** The callback is **unnecessary**. Signals are
already in `engine.signals`. Setting `on_signal` is optional — skip it.

The `SignalEventProcessor` class itself is a Path A adapter. Path B
bypasses it entirely.

### Protocol implications

The `SignalEngine` protocol currently requires `on_signal` getter/setter:

```python
class SignalEngine(Protocol):
    @property
    def on_signal(self) -> Callable[[TradeSignal], None] | None: ...
    @on_signal.setter
    def on_signal(self, callback: Callable[[TradeSignal], None] | None) -> None: ...
```

This is a Path A concern. If future engines only need Path B, the
callback can be removed from the protocol and kept as an optional mixin.
For now, both paths coexist without conflict — the callback is never
invoked unless explicitly wired.

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

### SignalEventProcessor

Location: `src/tastytrade/messaging/processors/signal.py`

Path A adapter. Wraps a `SignalEngine` in the `EventProcessor` interface
so it can be registered with `EventHandler.add_processor()`.

- Filters non-`CandleEvent` types (prevents re-entrant loops from
  `TradeSignal` being broadcast back through processors)
- Sets up `on_signal` callback to emit signals back into the handler chain

**Not needed for Path B.**

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
