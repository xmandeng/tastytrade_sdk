# TT-41: SPX 0DTE Hull+MACD Confluence Signal Detection Engine

## Context

The `playground_charts.ipynb` notebook manually computes Hull MA and MACD indicators on SPX candle data for visual analysis. There is no automated way to detect when both indicators align (confluence) and generate actionable trade signals. TT-41 builds a protocol-based signal detection engine that monitors real-time 5-minute candle data, detects Hull MA direction change + MACD crossover confluences, emits `TradeSignal` events persisted to InfluxDB, and logs each signal to Grafana Cloud via the existing observability pipeline.

This is the Phase 1 foundation for Epic TT-44 (Algorithmic Trading Signals). TT-42 (Signal Assessment) and TT-43 (Backtesting) both depend on this.

## Architecture

Follows the existing `MetricsEventProcessor -> MetricsTracker` pattern. All processors are registered on the Candle `EventHandler`, which broadcasts every `BaseEvent` to all processors:

```
CandleEvent (SPX{=5m}) arrives at EventHandler
  -> EventHandler broadcasts to ALL registered processors:
     -> CandleEventProcessor.process_event()        (stores candle data)
     -> TelegrafHTTPEventProcessor.process_event()   (writes candle to InfluxDB)
     -> SignalEventProcessor.process_event()          (routes to HullMacdEngine)
           -> HullMacdEngine detects confluence
           -> Creates TradeSignal (extends BaseAnnotation extends BaseEvent)
           -> Emits TradeSignal back to EventHandler via emit callback
           -> logger.info() with structured fields (stdout JSON + Grafana Cloud OTLP)

TradeSignal re-enters EventHandler processor chain:
     -> TelegrafHTTPEventProcessor.process_event()   (writes signal to InfluxDB)
     -> CandleEventProcessor.process_event()          (ignores -- not a candle)
     -> SignalEventProcessor.process_event()           (ignores -- not a CandleEvent)
```

**Key design**: TradeSignal extends `BaseAnnotation` which extends `BaseEvent`, so it flows naturally through the EventHandler's processor chain. The `SignalEventProcessor` accepts an `emit` callback (wired to the EventHandler) to submit generated signals back into the pipeline. This avoids hardcoded processor references -- any processor on the channel that can handle a `BaseEvent` subclass will pick it up.

## Core Signal Logic

### Position-aware state machine

The engine tracks per-symbol position state: `FLAT`, `BULLISH`, or `BEARISH`. This prevents duplicate opens and enforces strict one-position-at-a-time per symbol. Directions map to spread types: BULLISH = bull put spread, BEARISH = bear call spread.

**OPEN signals** (entry) require **confluence** -- both indicators must agree:
- Hull MA direction change and MACD crossover typically fire on **different candles**
- Once one indicator triggers, it stays "armed" indefinitely (no expiry window)
- Either indicator can fire first -- the second completes the confluence
- Only fires when position is FLAT

**CLOSE signals** (exit) require only **one indicator** to flip:
- Hull direction reversal OR MACD crossover in opposing direction
- Only fires when position is BULLISH or BEARISH
- After CLOSE -> position returns to FLAT (no immediate reverse)
- Engine must wait for fresh confluence before next OPEN

This asymmetry is intentional for 0DTE trading: strict confluence for entry (high confidence), single-indicator exit (fast capital protection).

## Implementation Plan

### Step 1: Create `src/tastytrade/analytics/engines/models.py`

**SignalDirection** enum (`BULLISH`, `BEARISH`), **SignalType** enum (`OPEN`, `CLOSE`), and **TradeSignal** model extending `BaseAnnotation`. BULLISH maps to bull put spread, BEARISH to bear call spread.

TradeSignal fields beyond BaseAnnotation:
- `signal_type: str` -- "OPEN" or "CLOSE"
- `direction: str` -- "BULLISH" or "BEARISH"
- `engine: str` -- engine name ("hull_macd")
- `hull_direction: str` -- "Up" or "Down"
- `hull_value: float` -- HMA value at signal time
- `macd_value: float` -- MACD line value
- `macd_signal: float` -- MACD signal line value
- `macd_histogram: float` -- MACD histogram value
- `close_price: float` -- triggering candle's close
- `trigger: str` -- which indicator triggered ("hull", "macd", or "confluence" for opens)
- `event_type: str = "trade_signal"` -- InfluxDB measurement name

Inherits from `BaseAnnotation` (`src/tastytrade/analytics/visualizations/models.py:90`) which provides `_ProcessorSafeDict` wrapping, `time` property with SHA-256 jitter, and all styling fields for chart rendering.

### Step 2: Create `src/tastytrade/analytics/engines/protocol.py`

**SignalEngine** protocol using `typing.Protocol` (structural subtyping):
- `name: str` property
- `signals: list[TradeSignal]` property
- `on_signal` property (getter/setter for `Callable[[TradeSignal], None]`) -- callback invoked when a signal fires
- `set_prior_close(event_symbol: str, price: float) -> None`
- `on_candle_event(event: CandleEvent) -> None`

### Step 3: Create `src/tastytrade/analytics/engines/__init__.py`

Package exports: `HullMacdEngine`, `SignalDirection`, `TradeSignal`, `SignalEngine`.

### Step 4: Create `src/tastytrade/analytics/engines/hull_macd.py`

Core engine with three internal mechanisms:

**a) DataFrame accumulation** -- Each CandleEvent is accumulated into a per-symbol `pl.DataFrame` using the same `vstack -> unique(keep="last") -> sort` pattern from `CandleEventProcessor` (`messaging/processors/default.py:80-86`). Capped at 500 candles.

**b) Indicator computation** -- Recomputes `hull()` and `macd()` on accumulated DataFrame each candle.
- `hull()` (`analytics/indicators/momentum.py:46`) returns `pd.DataFrame` with `HMA_color` ("Up"/"Down")
- `macd()` (`analytics/indicators/momentum.py:116`) returns `pl.DataFrame` with `Value` and `avg` columns
- MACD position: "bullish" when Value > avg, "bearish" otherwise

**c) Position-aware state machine** -- Per-symbol `TimeframeState` dataclass tracks:
- `hull_direction` / `macd_position` -- current indicator states
- `hull_armed_direction` / `macd_armed_direction` -- armed signal directions after change
- `position` -- current position: `FLAT`, `BULLISH`, or `BEARISH`

State machine flow depends on current position:

**When FLAT (looking for OPEN):**
1. Detect Hull direction **change** -> arm `hull_armed_direction`
2. Detect MACD position **change** -> arm `macd_armed_direction`
3. Both armed in same direction -> emit OPEN signal, set `position` to BULLISH/BEARISH, clear armed states
4. Both armed in opposing directions -> discard the older one

**When BULLISH (looking for CLOSE):**
5. Hull flips Down -> emit CLOSE signal, set `position` to FLAT, clear armed states
6. MACD crosses bearish -> emit CLOSE signal, set `position` to FLAT, clear armed states

**When BEARISH (looking for CLOSE):**
7. Hull flips Up -> emit CLOSE signal, set `position` to FLAT, clear armed states
8. MACD crosses bullish -> emit CLOSE signal, set `position` to FLAT, clear armed states

After any CLOSE, the engine returns to FLAT and all armed states are cleared. Fresh confluence is required for the next OPEN.

**d) Structured Grafana logging** -- On each signal, emit a structured `logger.info()` with all indicator snapshot fields as `extra` kwargs.

### Step 5: Create `src/tastytrade/messaging/processors/signal.py`

**SignalEventProcessor** -- thin adapter wrapping any `SignalEngine` for the `EventProcessor` protocol. Follows the `MetricsEventProcessor` pattern:
- `name = "signal"`
- `process_event()` -- routes `CandleEvent` to `engine.on_candle_event()`, ignores other event types
- `close()` -- logs final signal count
- Constructor accepts an `emit` callback wired to the EventHandler

### Step 6: Modify `src/tastytrade/messaging/processors/__init__.py`

Add `SignalEventProcessor` to imports and `__all__`.

### Step 7: Create `unit_tests/analytics/test_hull_macd_engine.py` (~34 tests)

Tests mock `hull()` and `macd()` via `@patch` to control indicator state deterministically.

### Step 8: Create `unit_tests/analytics/test_signal_processor.py` (~4 tests)

### Step 9: Quality gates

Run `uv run pytest`, `uv run mypy .`, `uv run ruff check .` -- all must pass clean.

### Step 10: Create `src/devtools/playground_signals.ipynb`

Verification notebook demonstrating signals on real SPX data with chart overlay.

## Files Summary

| Action | File | Description |
|--------|------|-------------|
| Create | `src/tastytrade/analytics/engines/__init__.py` | Package exports |
| Create | `src/tastytrade/analytics/engines/models.py` | SignalDirection + TradeSignal |
| Create | `src/tastytrade/analytics/engines/protocol.py` | SignalEngine protocol |
| Create | `src/tastytrade/analytics/engines/hull_macd.py` | HullMacdEngine (core) |
| Create | `src/tastytrade/messaging/processors/signal.py` | SignalEventProcessor adapter |
| Modify | `src/tastytrade/messaging/processors/__init__.py` | Add export |
| Create | `unit_tests/analytics/test_hull_macd_engine.py` | ~34 engine tests |
| Create | `unit_tests/analytics/test_signal_processor.py` | ~4 processor tests |
| Create | `src/devtools/playground_signals.ipynb` | Verification notebook |

## Key Dependencies (reuse existing)

- `hull()` -- `src/tastytrade/analytics/indicators/momentum.py:46`
- `macd()` -- `src/tastytrade/analytics/indicators/momentum.py:116`
- `BaseAnnotation` -- `src/tastytrade/analytics/visualizations/models.py:90`
- `CandleEvent` -- `src/tastytrade/messaging/models/events.py:149`
- `EventProcessor` protocol -- `src/tastytrade/messaging/processors/default.py:16`
- `TelegrafHTTPEventProcessor` -- `src/tastytrade/messaging/processors/influxdb.py:14`
- `parse_candle_symbol()` -- `src/tastytrade/utils/helpers.py:38`
- Observability pipeline -- `src/tastytrade/common/observability.py:44`
