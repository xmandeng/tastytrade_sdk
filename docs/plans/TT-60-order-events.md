# TT-60: Account Streamer Event Inventory & Implementation Plan

> **Jira:** [TT-60](https://mandeng.atlassian.net/browse/TT-60)
> **Branch:** `feature/TT-60-order-events`

## Context

The TastyTrade Account Streamer WebSocket delivers **9 distinct event types**, but our `AccountStreamer` only handles 2 (`CurrentPosition`, `AccountBalance`). The remaining 7 are either silently dropped (5 arrive via the `connect` action) or never subscribed to (2 require separate subscription actions).

This document inventories all event types with enough detail to make informed scoping decisions for TT-60 and follow-up tickets.

---

## Two Separate Streaming Pipelines

The separation between AccountStreamer and DXLink/MessageRouter is **architecturally justified** — they are different WebSocket APIs with incompatible protocols:

| | DXLink (MessageRouter) | Account Streamer |
|---|---|---|
| **Endpoint** | Dynamic URL from `/api-quote-tokens` (dxfeed.com) | `wss://streamer.tastyworks.com` |
| **Auth** | Quote token via `AuthModel` | Raw session token (no Bearer) |
| **Protocol** | Channel-based (numbered channels 0–99) | Flat event types, no channels |
| **Data domain** | Market data (Quote, Trade, Greeks, Candle…) | Account state (positions, balances, orders…) |
| **Hydration** | Pure streaming | Must REST-hydrate on every reconnect |

These cannot be merged. TT-60 work extends the **AccountStreamer pipeline only**.

---

## Complete Event Type Inventory

Source: [TastyTrade Streaming Account Data docs](https://developer.tastytrade.com/streaming-account-data/) cross-referenced with the [tastyware/tastytrade community SDK](https://github.com/tastyware/tastytrade/blob/master/tastytrade/streamer.py) `MAP_ALERTS` dictionary.

### Events arriving via `connect` action (already subscribed)

These 7 types arrive today. We handle 2 and silently drop 5.

---

#### 1. `CurrentPosition` — ✅ HANDLED

| Field | Value |
|---|---|
| **Wire name** | `CurrentPosition` |
| **Our model** | `Position` (`accounts/models.py:45`) |
| **Trigger** | Position quantity changes — fills modify quantity, new positions opened, positions closed |
| **Lifecycle role** | **Result of trades** — after an order fills, this fires with the updated position state |
| **Key fields** | `account-number`, `symbol`, `instrument-type`, `quantity`, `quantity-direction`, `average-open-price`, `mark`, `close-price`, `realized-day-gain`, `streamer-symbol` |
| **Redis key** | `tastytrade:positions` (HSET, field = symbol) |
| **Our status** | Fully implemented — parsed, queued, published to Redis |

---

#### 2. `AccountBalance` — ✅ HANDLED

| Field | Value |
|---|---|
| **Wire name** | `AccountBalance` |
| **Our model** | `AccountBalance` (`accounts/models.py:256`) |
| **Trigger** | Balance changes — fills, deposits, withdrawals, margin adjustments |
| **Lifecycle role** | **Financial impact of trades** — after a fill, fires with updated buying power, cash, margin |
| **Key fields** | `account-number`, `cash-balance`, `net-liquidating-value`, `equity-buying-power`, `derivative-buying-power`, `maintenance-requirement`, 48+ fields total |
| **Redis key** | `tastytrade:balances` (HSET, field = account-number) |
| **Our status** | Fully implemented — parsed, queued, published to Redis |

---

#### 3. `Order` — ❌ DROPPED

| Field | Value |
|---|---|
| **Wire name** | `Order` |
| **Community model** | `PlacedOrder` |
| **Trigger** | Every order state transition — placed, routed, live, partially filled, filled, cancelled, rejected, expired, replaced |
| **Lifecycle role** | **The order lifecycle itself** — each state change fires a new event with the full order representation. Fills are embedded in `legs[].fills[]` |
| **Key fields** | `id`, `account-number`, `time-in-force`, `order-type`, `size`, `underlying-symbol`, `underlying-instrument-type`, `status`, `cancellable`, `editable`, `legs[]` |
| **Leg fields** | `instrument-type`, `symbol`, `action` (Buy to Open, Sell to Close, etc.), `quantity`, `remaining-quantity`, `fills[]` |
| **Fill fields** | `fill-id`, `quantity`, `fill-price`, `filled-at`, `destination-venue`, `ext-exec-id` |
| **Status enum** | `Received`, `Routed`, `In Flight`, `Live`, `Filled`, `Cancelled`, `Expired`, `Rejected`, `Cancel Requested`, `Replace Requested`, `Removed`, `Partially Removed`, `Contingent` |
| **Additional fields (filled)** | `ext-exchange-order-number`, `ext-client-order-id`, `ext-global-order-number`, `received-at`, `updated-at`, `in-flight-at`, `live-at`, `terminal-at`, `destination-venue`, `user-id`, `username` |
| **Payload style** | Full object representation on every state change (not differential) |

---

#### 4. `ComplexOrder` — ❌ DROPPED

| Field | Value |
|---|---|
| **Wire name** | `ComplexOrder` |
| **Community model** | `PlacedComplexOrder` |
| **Trigger** | Multi-leg order state changes — OCO (one-cancels-other), OTOCO (one-triggers-OCO) |
| **Lifecycle role** | **Container for multi-leg strategies** — spreads, iron condors, strangles. Contains a list of sub-orders (`PlacedOrder`) that each have their own lifecycle |
| **Key fields** | `id`, `account-number`, `type` (OCO/OTOCO), `orders[]` (list of PlacedOrder), `trigger-order`, `terminal-at`, `ratio-price` |
| **Relationship to Order** | Each sub-order within also fires individual `Order` events. ComplexOrder provides the grouping context |
| **Use case** | Understanding that two legs are part of the same spread strategy |

---

#### 5. `ExternalTransaction` — ❌ DROPPED

| Field | Value |
|---|---|
| **Wire name** | `ExternalTransaction` |
| **Community model** | `ExternalTransaction` |
| **Trigger** | Money movements — deposits, withdrawals, ACH transfers, wire transfers |
| **Lifecycle role** | **Financial operations outside of trading** — tracks when money enters/leaves the account |
| **Key fields** | `id`, `account-number`, `amount`, `bank-account-type`, `banking-date`, `direction`, `disbursement-type`, `ext-transfer-id`, `funds-available-date`, `is-cancelable`, `is-clearing-accepted`, `state`, `transfer-method` |
| **Use case** | Knowing when a deposit clears and funds become available for trading |

---

#### 6. `TradingStatus` — ❌ DROPPED

| Field | Value |
|---|---|
| **Wire name** | `TradingStatus` |
| **Community model** | `TradingStatus` |
| **Trigger** | Account permission changes — futures approval, crypto enablement, margin calls, PDT status changes |
| **Lifecycle role** | **Account-level permissions and restrictions** — what the account can trade, any regulatory flags |
| **Key fields** | ~28 fields — `is-futures-enabled`, `is-cryptocurrency-enabled`, `is-margin-call`, `day-trade-count`, `pdt-reset-on`, `enhanced-fraud-safeguards-enabled-at` |
| **Use case** | Detecting margin calls, PDT violations, or permission changes that affect trading strategy |

---

#### 7. `UnderlyingYearGainSummary` — ❌ DROPPED

| Field | Value |
|---|---|
| **Wire name** | `UnderlyingYearGainSummary` |
| **Community model** | `UnderlyingYearGainSummary` |
| **Trigger** | Year-to-date P&L summary updates per underlying symbol |
| **Lifecycle role** | **Tax/P&L tracking** — aggregated realized gains and losses per symbol per year |
| **Key fields** | `year`, `account-number`, `symbol`, `instrument-type`, `fees`, `commissions`, `yearly-realized-gain`, `realized-lot-gain` |
| **Use case** | Real-time tax lot tracking, wash sale monitoring, year-end P&L dashboards |

---

### Events requiring separate subscription actions (not subscribed)

These 2 types require sending separate WebSocket messages beyond `connect`.

---

#### 8. `QuoteAlert` — 🔇 NOT SUBSCRIBED

| Field | Value |
|---|---|
| **Wire name** | `QuoteAlert` |
| **Community model** | `QuoteAlert` |
| **Subscription action** | `quote-alerts-subscribe` (separate from `connect`) |
| **Trigger** | User-configured price alerts trigger — e.g., "alert me when AAPL > $200" |
| **Key fields** | `user-external-id`, `symbol`, `alert-external-id`, `expires-at`, `completed-at`, `triggered-at`, `field`, `operator`, `threshold`, `threshold-numeric`, `dx-symbol` |
| **Use case** | Automated reaction to price targets — could trigger strategy evaluation |

---

#### 9. `PublicWatchlists` — 🔇 NOT SUBSCRIBED

| Field | Value |
|---|---|
| **Wire name** | `PublicWatchlists` |
| **Community model** | `Watchlist` |
| **Subscription action** | `public-watchlists-subscribe` (separate from `connect`) |
| **Trigger** | Public watchlist changes — TastyTrade-curated symbol lists |
| **Key fields** | `name`, `watchlist-entries[]`, `group-name`, `order-index` |
| **Use case** | Tracking TastyTrade's curated lists for market context or universe selection |

---

## Trade Lifecycle Flow

When a user places a single-leg order, the event sequence is:

```
1. Order (status: Received)      — order accepted by TastyTrade
2. Order (status: Routed)        — sent to exchange
3. Order (status: Live)          — active on exchange
4. Order (status: Filled)        — executed, legs[].fills[] populated
5. CurrentPosition               — position quantity updated
6. AccountBalance                — buying power, cash balance updated
7. UnderlyingYearGainSummary     — YTD P&L updated (may be delayed)
```

For multi-leg orders (spreads, iron condors):

```
1. ComplexOrder (contains sub-orders)
2. Order events for each leg independently
3. CurrentPosition events for each leg
4. AccountBalance event (aggregate impact)
```

For money movements:

```
1. ExternalTransaction (state changes: pending → cleared)
2. AccountBalance (when funds settle)
```

Key: **Notifications always contain the full object representation, not partial/differential updates.**

---

## Scoping Decisions (Finalized)

> Reviewed and approved 2026-03-02 via `TT-60-order-events-review.html`

| # | Wire Name | Action | Decision | Rationale |
|---|---|---|---|---|
| 1 | `CurrentPosition` | `connect` | ✅ Already done | — |
| 2 | `AccountBalance` | `connect` | ✅ Already done | — |
| 3 | `Order` | `connect` | ✅ **Include** | Core trade lifecycle. Events already arriving and being dropped. |
| 4 | `ComplexOrder` | `connect` | ✅ **Include** | Multi-leg strategy context. Most real-world orders are complex. |
| 5 | `ExternalTransaction` | `connect` | ⏭️ Skip | Money movements. Low frequency, different domain. Follow-up ticket. |
| 6 | `TradingStatus` | `connect` | ⏭️ Skip | Account permissions. Low frequency, operational concern. Follow-up ticket. |
| 7 | `UnderlyingYearGainSummary` | `connect` | ⏭️ Skip | P&L tracking. Useful but separate concern. Follow-up ticket. |
| 8 | `QuoteAlert` | `quote-alerts-subscribe` | ⏭️ Skip | Requires new subscription plumbing. Follow-up ticket. |
| 9 | `PublicWatchlists` | `public-watchlists-subscribe` | ⏭️ Skip | Requires new subscription plumbing. Low priority. Follow-up ticket. |

**TT-60 scope:** Order + ComplexOrder (complete trade lifecycle pipeline)

---

## Architecture Impact

### Current (`_handle_event` flow)

```
WebSocket → _handle_event() → parse_event() → Queue[EventType] → Publisher → Redis
                                    ↓
                              Unknown type?
                              → logger.warning()
                              → return (DROPPED)
```

### Proposed (for included types)

For each included event type, we need:

1. **Enum member** in `AccountEventType`
2. **Pydantic model** in `accounts/models.py` (following `TastyTradeApiModel` + `Field(alias=...)` pattern)
3. **Branch in `parse_event()`** for deserialization
4. **Queue** in `AccountStreamer.queues`
5. **Publisher method** in `AccountStreamPublisher`
6. **Redis key** convention (e.g., `tastytrade:orders`)
7. **Consumer coroutine** in `orchestrator.py`
8. **Unit tests** for parsing, routing, and publishing

The pattern is well-established by CurrentPosition and AccountBalance — each new type follows the same template.

---

## Decisions on Open Questions (Finalized)

> Reviewed and approved 2026-03-02 via `TT-60-order-events-review.html`

1. **Live payload validation** — **Collect data from sandbox first.** Capture real Order and ComplexOrder payloads from the sandbox (`TT_SANDBOX_*` creds in `.env`) before finalizing Pydantic model definitions. De-risks deeply nested structures (`legs[].fills[]`, `orders[]`).

2. **Model strictness** — **Compromise.** Start with `extra="ignore"` to tolerate undocumented fields and ship faster. Promote to `extra="forbid"` after validating against live sandbox payloads.

3. **Redis key design for orders** — **Separate key for ComplexOrder.** `tastytrade:orders` HSET (field = order ID) for Order events. `tastytrade:complex-orders` HSET (field = complex order ID) for ComplexOrder events. Keeps data model clean, avoids ID collisions.
