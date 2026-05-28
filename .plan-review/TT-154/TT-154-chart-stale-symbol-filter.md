# TT-154: Chart Symbol Dropdown Freshness Filter — Implementation Plan

> **Jira:** [TT-154](https://mandeng.atlassian.net/browse/TT-154)
> **Branch:** `feature/TT-154-chart-stale-symbol-filter`
> **Epic:** [TT-96](https://mandeng.atlassian.net/browse/TT-96) Market Data Visualization

## Problem

The chart UI symbol dropdown is populated by `/api/symbols`
(`src/tastytrade/charting/server.py`), which returns base symbols from
`RedisSubscriptionStore.get_active_subscriptions()`. Entries in the Redis
`subscriptions` hash are written `active: True` and only flipped to
`active: False` by an explicit unsubscribe or the orchestrator's clean-shutdown
finally-block. They are never aged out, so orphaned entries accumulate and show
up as stale symbols in the dropdown.

Orphans arise when a subscription process crashes before its cleanup runs, or
when a dead process's position symbols (added by the in-memory, per-process
`PositionSymbolResolver`) are never un-marked by a fresh process.

## Scope — chart only

Only the dropdown is affected. The running subscription service does **not**
rely on the Redis `active` set to decide what to subscribe on reconnect — it
re-derives the set from the launch `--symbols` list plus a live
`PositionSymbolResolver` pass (`subscription/orchestrator.py`). The
`subscriptions` hash is effectively a display/diagnostic projection, so
filtering the chart's *view* of it carries no recovery or durability risk.

## Approach — read-time freshness filter

Filter inside the `/api/symbols` endpoint **only**. Exclude candle
subscriptions whose `last_update` is older than a threshold. `last_update` is
bumped on every incoming event (`messaging/handlers.py`), so live symbols stay
fresh while orphans (frozen `last_update`) age out of the view. No writes, no
TTL, no schema change, no change to `get_active_subscriptions()` or any
recovery path. Fully reversible.

### Threshold

`CHART_SYMBOL_STALE_DAYS`, default **4 days**, env-overridable. Matches the
resolver's documented "backfill 4 days to cover weekends + holidays" window and
clears the worst realistic market gap (~3.7-day holiday weekend) with margin
while still hiding ghosts from older dead processes.

## Changes

`src/tastytrade/charting/server.py`:
1. `import os`.
2. Add module constant `CHART_SYMBOL_STALE_DAYS` read from env (default 4).
3. Add pure helper `fresh_base_symbols(subscriptions, now, max_age) -> set[str]`
   — candle-feed filter + freshness check + suffix strip. Entries with a
   missing/unparseable `last_update` are excluded (no silent "assume fresh"
   fallback).
4. `/api/symbols` calls the helper instead of the inline set comprehension.

## Non-goals

- No per-key TTL or Redis schema change.
- No producer-side cleanup changes.
- No changes to `status.py`, `restore_subscriptions`, or `get_reconnect_start`.

## Testing

- Unit-test `fresh_base_symbols` (pure, no Redis): fresh kept, stale dropped,
  missing/unparseable `last_update` dropped, ticker (non-`{=`) entries ignored,
  base-symbol dedup across intervals.
- Functional: against real Redis subscription data, show a stale entry absent
  from `/api/symbols` while fresh entries remain (per AC6).
