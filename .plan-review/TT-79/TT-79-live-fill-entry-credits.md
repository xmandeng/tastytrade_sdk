# TT-79: Live-Fill Entry Credit Updates for Option Positions — Implementation Plan

> **Jira:** [TT-79](https://mandeng.atlassian.net/browse/TT-79)
> **Branch:** `feature/TT-79-live-fill-entry-credits`
> **Depends on:** TT-63 (merged) — TransactionsClient, LIFO algorithm, EntryCredit model, Redis schema

---

## Problem

TT-63 computes entry credits **once at startup** by fetching historical transactions and running LIFO replay. While the system is running, new fills (opens, closes, legging in/out) are not reflected in Redis entry credits. The strategy classifier operates on stale cost basis data until the next restart.

## Solution

Subscribe to the `tastytrade:events:Order` Redis pub/sub channel. When a filled order with option legs is detected, re-fetch transactions for the affected symbols and recompute entry credits via LIFO replay. Clean up entry credits for fully closed positions.

## Architecture

```
WebSocket → AccountStreamer → ORDER queue → consume_orders → publisher.publish_order
                                                                    ↓
                                                          Redis pub/sub: tastytrade:events:Order
                                                                    ↓
                                                     monitor_fills_for_entry_credits  ← NEW
                                                          ↓                    ↓
                                                   qty > 0:              qty == 0:
                                                   re-fetch txns         remove_entry_credit()
                                                   LIFO replay
                                                   publish_entry_credits()
                                                          ↓
                                                   Redis pub/sub: tastytrade:events:EntryCreditsUpdated
                                                          ↓
                                                   Downstream consumers (strategy classifier)
```

**Why react to Order fills (not Position changes)?**
- Position events fire on mark-to-market updates — would trigger wasteful recomputation
- Order fill events are targeted: we know exactly when a trade happened
- Order legs tell us which symbols and instrument types are affected

---

## Implementation Steps

### Step 1: Create fill monitor function

**File:** `src/tastytrade/accounts/orchestrator.py`

New async function `monitor_fills_for_entry_credits()`:

```python
async def monitor_fills_for_entry_credits(
    redis: aioredis.Redis,
    session: aiohttp.ClientSession,
    account_number: str,
    publisher: AccountStreamPublisher,
) -> None:
    """React to filled orders by recomputing entry credits for affected option symbols."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(publisher.ORDER_CHANNEL)
    try:
        async for message in pubsub.listen():
            # Skip Redis subscription control messages (subscribe, psubscribe, etc.)
            # These are expected on initial subscribe and carry no order data.
            if message["type"] != "message":
                continue

            try:
                order = PlacedOrder.model_validate_json(message["data"])
            except ValidationError:
                # Malformed or schema-incompatible order payload.
                # Log and skip — do not crash the monitor for one bad message.
                logger.warning("Failed to parse Order event, skipping message")
                continue

            # Only process filled orders — ROUTED, LIVE, CANCELLED, EXPIRED, etc.
            # are intermediate states that do not represent executed trades.
            if order.status != OrderStatus.FILLED:
                continue

            # Extract option symbols from filled legs.
            # Orders with only equity or futures (non-option) legs are irrelevant
            # since entry credits only apply to option positions.
            option_symbols = extract_option_symbols(order)
            if not option_symbols:
                continue

            try:
                # Look up current position quantities from Redis
                positions_map = await resolve_position_quantities(
                    redis, option_symbols, publisher.POSITIONS_KEY
                )

                # Symbols with qty > 0: recompute entry credits
                if positions_map:
                    txn_client = TransactionsClient(session)
                    all_txns = await txn_client.get_transactions(account_number)
                    entry_credits = compute_entry_credits_for_positions(
                        all_txns, positions_map
                    )
                    if entry_credits:
                        await publisher.publish_entry_credits(entry_credits)
                        logger.info(
                            "Updated entry credits for %d symbols on fill",
                            len(entry_credits),
                        )

                # Symbols with qty == 0: clean up
                closed_symbols = set(option_symbols) - set(positions_map.keys())
                for symbol in closed_symbols:
                    await publisher.remove_entry_credit(symbol)

            except aiohttp.ClientError:
                # Network error fetching transactions from REST API.
                # Non-fatal — the next fill or restart will correct the data.
                logger.warning(
                    "Transaction fetch failed for fill on %d symbols, will retry on next fill",
                    len(option_symbols),
                )
            except Exception:
                # Unexpected error during entry credit computation.
                # Log and continue — don't let one failed update kill the monitor.
                logger.exception("Unexpected error processing fill for entry credits")

    finally:
        await pubsub.unsubscribe(publisher.ORDER_CHANNEL)
        await pubsub.close()
```

### Step 2: Add helper functions

**File:** `src/tastytrade/accounts/orchestrator.py`

```python
OPTION_TYPES = {InstrumentType.EQUITY_OPTION, InstrumentType.FUTURE_OPTION}

def extract_option_symbols(order: PlacedOrder) -> list[str]:
    """Extract unique option symbols from a filled order's legs."""
    return list({
        leg.symbol
        for leg in order.legs
        if leg.instrument_type in OPTION_TYPES
    })

async def resolve_position_quantities(
    redis: aioredis.Redis,
    symbols: list[str],
    positions_key: str,
) -> dict[str, int]:
    """Look up current position quantities from Redis for the given symbols.
    Returns only symbols with non-zero quantity."""
    positions_map: dict[str, int] = {}
    for symbol in symbols:
        raw = await redis.hget(positions_key, symbol)
        if raw is None:
            continue
        position = Position.model_validate_json(raw)
        qty = int(abs(position.quantity))
        if qty > 0:
            positions_map[symbol] = qty
    return positions_map
```

### Step 3: Wire into orchestrator

**File:** `src/tastytrade/accounts/orchestrator.py`

In `run_account_stream_once()`, after the existing consumer tasks are created, add the fill monitor task:

```python
fill_monitor_task = asyncio.create_task(
    monitor_fills_for_entry_credits(
        redis=redis_client,
        session=streamer.session,
        account_number=credentials.account_number,
        publisher=publisher,
    )
)
```

Add to the task group that gets awaited/cancelled on disconnect.

### Step 4: Expose publisher constants

**File:** `src/tastytrade/accounts/publisher.py`

Ensure `ORDER_CHANNEL` and `POSITIONS_KEY` are accessible as class attributes (they likely already are — verify and expose if not).

### Step 5: Unit tests

**File:** `unit_tests/accounts/test_fill_monitor.py`

Tests to write:
1. **Filled order with option legs triggers recomputation** — mock Redis pub/sub, verify `compute_entry_credits_for_positions` called with correct symbols
2. **Non-filled order is ignored** — ROUTED, LIVE, CANCELLED orders should not trigger anything
3. **Order with no option legs is ignored** — equity-only or futures-only orders skip
4. **Closed position cleanup** — when position qty == 0 in Redis, `remove_entry_credit` is called
5. **Mixed fill** — order with both option and non-option legs only processes option legs
6. **`extract_option_symbols` returns unique symbols** — deduplication
7. **`resolve_position_quantities` skips missing/zero positions** — returns only live positions

### Step 6: Type checking & linting

```bash
uv run pyright src/tastytrade/accounts/orchestrator.py
uv run ruff check src/tastytrade/accounts/orchestrator.py
uv run pytest -q
```

### Step 7: Functional testing

1. Start account-stream with updated code
2. Place an option order (or wait for a fill on an existing order)
3. Verify Redis entry credits update within seconds of fill
4. Close a position, verify entry credit removed from Redis

---

## Files Changed

| File | Change |
|------|--------|
| `src/tastytrade/accounts/orchestrator.py` | Add `monitor_fills_for_entry_credits`, `extract_option_symbols`, `resolve_position_quantities`; wire task into `run_account_stream_once` |
| `src/tastytrade/accounts/publisher.py` | Expose `ORDER_CHANNEL`, `POSITIONS_KEY` as class-level constants (if not already) |
| `unit_tests/accounts/test_fill_monitor.py` | New — unit tests for fill detection and entry credit recomputation |

## Design Decisions

1. **Redis pub/sub over queue splitting** — The ORDER asyncio.Queue is already consumed by `consume_orders`. Rather than splitting it or adding a second consumer, we subscribe to the Redis pub/sub channel that `publish_order` emits to. This follows the existing decoupled pattern.

2. **Full transaction re-fetch on fill** — Rather than incrementally updating the LIFO state, we re-fetch all transactions and re-run the replay. This is simpler, correct by construction, and the REST call is cheap (< 200ms). Incremental LIFO would be an optimization for later if needed.

3. **Position quantity from Redis** — We look up current quantities from `tastytrade:positions` HSET rather than maintaining separate state. By the time we process the order through Redis pub/sub, the position update from `consume_positions` has typically already landed.

4. **No debouncing** — Multi-leg orders (spreads, condors) arrive as a single filled order with multiple legs. We process all affected symbols in one pass, so no debouncing is needed.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Position not yet updated when fill monitor runs | Position events and order events arrive concurrently — position typically lands first. If not, the next fill or restart corrects it. |
| High-frequency fills cause transaction API hammering | Unlikely for this account's trading frequency. If needed, add a per-symbol cooldown. |
| Redis pub/sub message missed during reconnection | The self-healing orchestrator restarts from scratch (including startup entry credit computation), so no data is permanently lost. |
