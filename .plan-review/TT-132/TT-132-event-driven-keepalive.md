# TT-132: Event-driven DXLink keepalive — Reduced-Scope Plan

> **Jira:** [TT-132](https://mandeng.atlassian.net/browse/TT-132)
> **Branch:** `feature/TT-132-remove-unused-keepalive-event`
> **Status:** Reviewed 2026-05-09 — refactor declined; minimal cleanup approved

## Review Outcome

The plan-review of the proposed event-driven refactor concluded that **the refactor should not proceed**. The original ticket asked us to drive `send_keepalives()` off the unused `self.keepalive_stop = asyncio.Event()` field instead of `while True` + `asyncio.sleep(30)`. Side-by-side, every alternative we considered traded clean code for rule-compliance:

| Approach | New problem introduced |
|---|---|
| `while not self.keepalive_stop.is_set():` + `wait_for(..., timeout=30)` | Nested `try/except`, with `TimeoutError` used as positive control flow ("timeout means keep going"). |
| `@property keepalive_running` wrapper | Same exception abuse, plus a property whose only job is to invert another field. |
| Two events / `asyncio.wait` with `FIRST_COMPLETED` | Manual task lifecycle management around a primitive that already cooperates with cancellation. |

The current code is **already event-driven in the way that matters**: `asyncio.sleep(30)` yields to the loop and is interruptible by `task.cancel()` from `close()`. The existing `except asyncio.CancelledError` branch handles graceful shutdown. There is no busy-loop, no ignored signals, and no measurable performance or latency cost.

The CLAUDE.md rule — *"Avoid `while True` (infinite) loops — react to events instead"* — is aimed at polling loops that ignore real signals (Redis pub/sub, asyncio.Event, queue.get). A cooperative 30-second `asyncio.sleep` driving a heartbeat is exactly the shape the rule is *not* trying to forbid.

## Reduced Scope

The only legitimate code smell the ticket exposed was the **unused `self.keepalive_stop = asyncio.Event()` field** at `src/tastytrade/connections/sockets.py:105`. It was wired up by an earlier author for exactly this refactor and never consumed — it lies about the file's intent. Delete it.

**That is the entire change.**

## Files Touched

- `src/tastytrade/connections/sockets.py` — remove line 105 (`self.keepalive_stop = asyncio.Event()`)

## Acceptance Criteria

- `self.keepalive_stop` initialization removed from `DXLinkManager.__init__`
- No remaining references to `keepalive_stop` anywhere in the repo
- `send_keepalives()` and `close()` are **unchanged** — `while True` + `asyncio.sleep(30)` + cancellation-driven shutdown remain in place
- `uv run pytest` passes
- `uv run pyright` passes
- `uv run ruff check` passes

## Verification

- **Unit/integration:** existing test suite must pass without modification.
- **Functional:** start a real DXLink session via `tasty-subscription`, observe `Keepalive sent from client` at ~30s cadence, and SIGINT to confirm `close()` still cleans up. (Behavior is unchanged from main, so this is a regression check, not a new-feature evidence run.)

## Risk

Trivial — deletion of an unreferenced field. No behavior change.

## Out of Scope

- The originally proposed event-driven refactor of `send_keepalives()` (declined for the reasons above)
- Any change to `close()` task-cancellation
- Any change to `socket_listener()`'s `async for` loop
