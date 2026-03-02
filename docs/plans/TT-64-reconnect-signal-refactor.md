# TT-64: Refactor Reconnection Signaling — Implementation Plan

> **Jira:** [TT-64](https://mandeng.atlassian.net/browse/TT-64)
> **Branch:** `feature/TT-64-reconnect-signal-refactor`

## Problem

ControlHandler uses a callback to signal reconnection back through DXLinkManager, creating a circular dependency and hidden control flow that can't be represented in the architecture diagram. Additionally, three separate reconnection sources (socket_listener, send_keepalives, ControlHandler) each call `trigger_reconnect()` directly, bypassing the existing message pipeline.

## Approach

**Simplified event-driven state machine. All reconnection events flow through a single pipeline.**

1. **Queue[0] as the single event bus** — all failure events enter through the control queue. `socket_listener()` and `send_keepalives()` place CONNECTION_DROPPED messages into `Queue[0]` on failure. Server-sent events (AUTH_EXPIRED, TIMEOUT, PROTOCOL_ERROR) already arrive here naturally.

2. **ControlHandler as the state machine** — evaluates every control event and decides whether to trigger a reconnection. Single authority — no other component makes reconnection decisions.

3. **ReconnectSignal as the stable mailbox** — ControlHandler calls `signal.trigger(reason)`, Orchestrator awaits `signal.wait()`. The signal outlives ControlHandler across reconnection cycles.

4. **One signal path** — failure source → Queue[0] → ControlHandler → ReconnectSignal → Orchestrator. No callbacks. No circular dependencies.

### Key Design Decision

socket_listener and send_keepalives can still reach Queue[0] when the WebSocket is dead because the queues are in-memory `asyncio.Queue` objects on DXLinkManager — they survive the socket dying. The MessageRouter's queue reader loop is still running.

### What Changes

| Component | Before | After |
|---|---|---|
| socket_listener | `self.trigger_reconnect()` | `await self.queues[0].put(connection_dropped_msg)` |
| send_keepalives | `self.trigger_reconnect()` | `await self.queues[0].put(connection_dropped_msg)` |
| ControlHandler | `callback(reason)` → DXLinkManager | `signal.trigger(reason)` → ReconnectSignal |
| DXLinkManager | Owns reconnect_event, trigger_reconnect(), wait_for_reconnect_signal() | No reconnect methods; failure tasks place messages into Queue[0] |
| MessageRouter | Forwards callback to ControlHandler | Routes messages to queues only |
| Orchestrator | `await dxlink.wait_for_reconnect_signal()` | `await signal.wait()` |

### New File

`connections/signals.py` — `ReconnectSignal` class with `trigger(reason)` and `async wait()` methods. A stable mailbox that outlives ControlHandler across reconnection cycles — ControlHandler is torn down and recreated on every reconnect, so the Orchestrator cannot subscribe to it directly. Instead, the Orchestrator creates this signal once and passes it down; each new ControlHandler instance publishes to the same object.
