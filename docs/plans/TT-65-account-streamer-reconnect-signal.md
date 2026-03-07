# TT-65: Apply ReconnectSignal Refactor to AccountStreamer — Implementation Plan

> **Status:** COMPLETED — AccountStreamer refactored to use shared ReconnectSignal. This plan is historical reference.

> **Jira:** [TT-65](https://mandeng.atlassian.net/browse/TT-65)
> **Branch:** `feature/TT-65-account-streamer-reconnect-signal`
> **Depends on:** [TT-64](https://mandeng.atlassian.net/browse/TT-64) (Done)

## Problem

AccountStreamer embeds its own reconnection state (`reconnect_event`, `reconnect_reason`, `should_reconnect`) and exposes `trigger_reconnect()` / `wait_for_reconnect_signal()` methods directly on the singleton. This diverges from the subscription streamer, which uses a standalone `ReconnectSignal` object created by the orchestrator and injected into the pipeline. The inconsistency:

- Breaks semantic parity across the two streamers
- Ties reconnection lifecycle to the singleton (destroyed/recreated each cycle)
- Makes external producers (failure simulation) reach into AccountStreamer internals
- Prevents sharing `ReconnectSignal` with future components

## Architecture — Before

```
┌──────────────────────────────────────────────┐
│           AccountStreamer (singleton)         │
│                                              │
│  reconnect_event: asyncio.Event  ← embedded  │
│  reconnect_reason: ReconnectReason           │
│  should_reconnect: bool                      │
│                                              │
│  socket_listener ──► trigger_reconnect()     │
│  send_keepalives ──► trigger_reconnect()     │
│                          │                   │
│                          ▼                   │
│              wait_for_reconnect_signal()      │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│      Account Stream Orchestrator             │
│                                              │
│  monitor = streamer.wait_for_reconnect_signal│
│  await monitor  →  raise ConnectionError     │
└──────────────────────────────────────────────┘
```

## Architecture — After

```
┌──────────────────────────┐     ┌────────────────────────┐
│  Account Stream          │     │   ReconnectSignal      │
│  Orchestrator            │     │   (connections/        │
│                          │     │    signals.py)         │
│  signal = ReconnectSignal│────►│                        │
│                          │     │  .trigger(reason)      │
│  AccountStreamer(         │     │  .wait() → reason      │
│    signal=signal)        │     │  .reset()              │
│                          │     └───────────┬────────────┘
│  await signal.wait()  ◄──────────────────-─┘
│    → raise ConnectionError                  │
└──────────────────────────┘                  │
                                              │
┌─────────────────────────────────────────────┘
│
│  ┌──────────────────────────────────────────────┐
│  │           AccountStreamer                     │
│  │                                              │
│  │  self.reconnect_signal: ReconnectSignal      │
│  │                                              │
│  │  socket_listener ──► signal.trigger(         │
│  │                        CONNECTION_DROPPED)   │
│  │  send_keepalives ──► signal.trigger(         │
│  │                        CONNECTION_DROPPED)   │
│  └──────────────────────────────────────────────┘
```

## What Changes

| Component | Before | After |
|---|---|---|
| AccountStreamer.__init__ | Owns `reconnect_event`, `should_reconnect`, `reconnect_reason` | Accepts `ReconnectSignal` parameter |
| socket_listener | `self.trigger_reconnect(reason)` | `self.reconnect_signal.trigger(reason)` |
| send_keepalives | `self.trigger_reconnect(reason)` | `self.reconnect_signal.trigger(reason)` |
| trigger_reconnect() | Method on AccountStreamer | Removed — use `signal.trigger()` |
| wait_for_reconnect_signal() | Method on AccountStreamer | Removed — use `signal.wait()` |
| should_reconnect | Bool flag checked in error handlers | Check `self.reconnect_signal is not None` |
| Orchestrator | `streamer.wait_for_reconnect_signal()` | `signal.wait()` |
| close() | Sets `should_reconnect = False` | No reconnect flag to clear |

## Implementation Steps

1. **Modify AccountStreamer.__init__** — accept optional `ReconnectSignal`, remove embedded state
2. **Update socket_listener** — call `self.reconnect_signal.trigger()` instead of `self.trigger_reconnect()`
3. **Update send_keepalives** — same as above
4. **Remove methods** — `trigger_reconnect()`, `wait_for_reconnect_signal()`
5. **Update close()** — remove `should_reconnect = False`
6. **Update orchestrator** — create `ReconnectSignal`, pass to `AccountStreamer`, monitor with `signal.wait()`
7. **Update tests** — verify signal-based behavior

## Files Modified

| File | Change |
|------|--------|
| `src/tastytrade/accounts/streamer.py` | Remove embedded state, accept ReconnectSignal |
| `src/tastytrade/accounts/orchestrator.py` | Create signal, inject, monitor |
| `unit_tests/accounts/test_account_streamer.py` | Update for signal-based assertions |
| `unit_tests/accounts/test_account_orchestrator.py` | Update orchestrator tests |
