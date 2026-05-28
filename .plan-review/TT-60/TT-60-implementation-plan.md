# TT-60: Order & ComplexOrder Event Pipeline — Implementation Plan

> **Status:** COMPLETED — Order event pipeline implemented. This plan is historical reference.

> **Jira:** [TT-60](https://mandeng.atlassian.net/browse/TT-60)
> **Branch:** `feature/TT-60-order-events`
> **Scope:** Order + ComplexOrder events (approved 2026-03-02)
> **Prerequisites:** Review decisions in `docs/plans/TT-60-order-events.md`

---

## Decisions (from review)

- **Scope:** Order + ComplexOrder only. All others deferred.
- **Payload validation:** Capture live sandbox payloads before finalizing models.
- **Model strictness:** Start with `extra="ignore"`, promote to `extra="forbid"` after sandbox validation.
- **Redis keys:** `tastytrade:orders` (field = order ID), `tastytrade:complex-orders` (field = complex order ID). Separate keys.

---

## Step 0: Capture Sandbox Payloads

**Goal:** Get real Order and ComplexOrder JSON payloads from the sandbox to validate model definitions before coding.

**Approach:**
1. Temporarily modify `AccountStreamer._handle_event()` to log raw payloads for unknown types
2. Connect to sandbox (`TT_SANDBOX_*` creds), place an order via the TastyTrade UI or API
3. Capture the full JSON for `Order` and `ComplexOrder` events
4. Save sample payloads to `docs/plans/TT-60-sample-payloads.json`
5. Revert the logging change

**Output:** Sample payloads that inform model field definitions in Step 2.

---

## Step 1: Extend AccountEventType Enum

**File:** `src/tastytrade/config/enumerations.py` (lines 78–82)

```python
class AccountEventType(str, Enum):
    """Event types from the TastyTrade Account Streamer WebSocket."""

    CURRENT_POSITION = "CurrentPosition"
    ACCOUNT_BALANCE = "AccountBalance"
    ORDER = "Order"                      # NEW
    COMPLEX_ORDER = "ComplexOrder"        # NEW
```

Wire names are case-sensitive and must match exactly. The `str, Enum` base ensures `AccountEventType("Order")` works in `_handle_event`.

---

## Step 2: Define Pydantic Models

**File:** `src/tastytrade/accounts/models.py`

Follow the established pattern: `TastyTradeApiModel` base, `Field(alias="kebab-case")`, `FloatFieldMixin` for numeric fields, `extra="ignore"` (per review decision).

### 2a: Supporting Enums

```python
class OrderStatus(str, Enum):
    RECEIVED = "Received"
    ROUTED = "Routed"
    IN_FLIGHT = "In Flight"
    LIVE = "Live"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"
    REJECTED = "Rejected"
    CANCEL_REQUESTED = "Cancel Requested"
    REPLACE_REQUESTED = "Replace Requested"
    REMOVED = "Removed"
    PARTIALLY_REMOVED = "Partially Removed"
    CONTINGENT = "Contingent"
    UNKNOWN = "Unknown"

class OrderAction(str, Enum):
    BUY_TO_OPEN = "Buy to Open"
    BUY_TO_CLOSE = "Buy to Close"
    SELL_TO_OPEN = "Sell to Open"
    SELL_TO_CLOSE = "Sell to Close"
    UNKNOWN = "Unknown"

class ComplexOrderType(str, Enum):
    OCO = "OCO"
    OTOCO = "OTOCO"
    UNKNOWN = "Unknown"

class PriceEffect(str, Enum):
    CREDIT = "Credit"
    DEBIT = "Debit"
    NONE = "None"
    UNKNOWN = "Unknown"

class TimeInForce(str, Enum):
    DAY = "Day"
    GTC = "GTC"
    GTD = "GTD"
    IOC = "IOC"
    UNKNOWN = "Unknown"

class OrderType(str, Enum):
    LIMIT = "Limit"
    MARKET = "Market"
    STOP = "Stop"
    STOP_LIMIT = "Stop Limit"
    UNKNOWN = "Unknown"
```

Each enum gets an `UNKNOWN` fallback + `@field_validator` coercion pattern (matching `InstrumentType` pattern at line 172).

### 2b: Nested Models (Fills, Legs)

```python
class OrderFill(TastyTradeApiModel, FloatFieldMixin):
    """A single fill execution within an order leg."""
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    fill_id: str = Field(alias="fill-id")
    quantity: float = Field(alias="quantity")
    fill_price: float = Field(alias="fill-price")
    filled_at: datetime = Field(alias="filled-at")
    destination_venue: Optional[str] = Field(default=None, alias="destination-venue")
    ext_exec_id: Optional[str] = Field(default=None, alias="ext-exec-id")
    ext_group_fill_id: Optional[str] = Field(default=None, alias="ext-group-fill-id")

    convert_float = FloatFieldMixin.validate_float_fields("quantity", "fill_price")


class OrderLeg(TastyTradeApiModel, FloatFieldMixin):
    """A single leg within an order."""
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    instrument_type: InstrumentType = Field(alias="instrument-type")
    symbol: str = Field(alias="symbol")
    action: OrderAction = Field(alias="action")
    quantity: float = Field(alias="quantity")
    remaining_quantity: Optional[float] = Field(default=None, alias="remaining-quantity")
    fills: list[OrderFill] = Field(default_factory=list, alias="fills")

    convert_float = FloatFieldMixin.validate_float_fields("quantity", "remaining_quantity")

    @field_validator("action", mode="before")
    @classmethod
    def coerce_unknown_action(cls, value: Any) -> str:
        try:
            OrderAction(value)
        except ValueError:
            logger.warning("Unknown order action '%s', mapping to UNKNOWN", value)
            return OrderAction.UNKNOWN.value
        return value
```

### 2c: PlacedOrder Model

```python
class PlacedOrder(TastyTradeApiModel, FloatFieldMixin):
    """A single order from the Account Streamer."""
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    # Identity
    id: int = Field(alias="id")
    account_number: str = Field(alias="account-number")

    # Order parameters
    order_type: OrderType = Field(alias="order-type")
    time_in_force: TimeInForce = Field(alias="time-in-force")
    price: Optional[float] = Field(default=None, alias="price")
    price_effect: Optional[PriceEffect] = Field(default=None, alias="price-effect")
    size: Optional[int] = Field(default=None, alias="size")

    # Status
    status: OrderStatus = Field(alias="status")
    cancellable: bool = Field(default=False, alias="cancellable")
    editable: bool = Field(default=False, alias="editable")

    # Underlying
    underlying_symbol: Optional[str] = Field(default=None, alias="underlying-symbol")
    underlying_instrument_type: Optional[InstrumentType] = Field(
        default=None, alias="underlying-instrument-type"
    )

    # Legs
    legs: list[OrderLeg] = Field(default_factory=list, alias="legs")

    # Timestamps
    received_at: Optional[datetime] = Field(default=None, alias="received-at")
    updated_at: Optional[datetime] = Field(default=None, alias="updated-at")
    in_flight_at: Optional[datetime] = Field(default=None, alias="in-flight-at")
    live_at: Optional[datetime] = Field(default=None, alias="live-at")
    terminal_at: Optional[datetime] = Field(default=None, alias="terminal-at")

    # Exchange routing
    destination_venue: Optional[str] = Field(default=None, alias="destination-venue")

    convert_float = FloatFieldMixin.validate_float_fields("price")

    @field_validator("status", mode="before")
    @classmethod
    def coerce_unknown_status(cls, value: Any) -> str:
        try:
            OrderStatus(value)
        except ValueError:
            logger.warning("Unknown order status '%s', mapping to UNKNOWN", value)
            return OrderStatus.UNKNOWN.value
        return value

    @field_validator("order_type", mode="before")
    @classmethod
    def coerce_unknown_order_type(cls, value: Any) -> str:
        try:
            OrderType(value)
        except ValueError:
            logger.warning("Unknown order type '%s', mapping to UNKNOWN", value)
            return OrderType.UNKNOWN.value
        return value

    @field_validator("time_in_force", mode="before")
    @classmethod
    def coerce_unknown_tif(cls, value: Any) -> str:
        try:
            TimeInForce(value)
        except ValueError:
            logger.warning("Unknown time-in-force '%s', mapping to UNKNOWN", value)
            return TimeInForce.UNKNOWN.value
        return value
```

### 2d: PlacedComplexOrder Model

```python
class PlacedComplexOrder(TastyTradeApiModel):
    """A complex (multi-leg) order from the Account Streamer."""
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    # Identity
    id: int = Field(alias="id")
    account_number: str = Field(alias="account-number")

    # Type
    type: ComplexOrderType = Field(alias="type")

    # Sub-orders
    orders: list[PlacedOrder] = Field(default_factory=list, alias="orders")
    trigger_order: Optional[PlacedOrder] = Field(default=None, alias="trigger-order")

    # Status
    terminal_at: Optional[datetime] = Field(default=None, alias="terminal-at")

    @field_validator("type", mode="before")
    @classmethod
    def coerce_unknown_type(cls, value: Any) -> str:
        try:
            ComplexOrderType(value)
        except ValueError:
            logger.warning("Unknown complex order type '%s', mapping to UNKNOWN", value)
            return ComplexOrderType.UNKNOWN.value
        return value
```

**Note:** Field lists are preliminary — Step 0 sandbox captures may reveal additional fields. Since `extra="ignore"`, undocumented fields won't cause failures.

---

## Step 3: Update AccountStreamer Routing

**File:** `src/tastytrade/accounts/streamer.py`

### 3a: Update imports and type annotations

```python
from tastytrade.accounts.models import (
    AccountBalance, PlacedComplexOrder, PlacedOrder, Position
)

# Update queue type (line 82):
self.queues: dict[
    AccountEventType,
    asyncio.Queue[Union[Position, AccountBalance, PlacedOrder, PlacedComplexOrder]]
] = {event_type: asyncio.Queue() for event_type in AccountEventType}
```

### 3b: Update parse_event (line 307–323)

```python
@staticmethod
def parse_event(
    event_type: str,
    data: dict,
) -> Union[Position, AccountBalance, PlacedOrder, PlacedComplexOrder, None]:
    """Parse event data into the corresponding Pydantic model."""
    try:
        if event_type == AccountEventType.CURRENT_POSITION:
            return Position.model_validate(data)
        elif event_type == AccountEventType.ACCOUNT_BALANCE:
            return AccountBalance.model_validate(data)
        elif event_type == AccountEventType.ORDER:
            return PlacedOrder.model_validate(data)
        elif event_type == AccountEventType.COMPLEX_ORDER:
            return PlacedComplexOrder.model_validate(data)
        else:
            logger.warning("Unknown event type for parsing: %s", event_type)
            return None
    except Exception as e:
        logger.warning("Failed to parse %s event: %s", event_type, e)
        return None
```

No other changes to `_handle_event` — the enum lookup (line 295) and queue routing (line 300) already handle any `AccountEventType` member automatically.

---

## Step 4: Add Publisher Methods

**File:** `src/tastytrade/accounts/publisher.py`

### 4a: Add imports and keys

```python
from tastytrade.accounts.models import (
    AccountBalance, PlacedComplexOrder, PlacedOrder, Position
)

class AccountStreamPublisher:
    POSITIONS_KEY = "tastytrade:positions"
    BALANCES_KEY = "tastytrade:balances"
    INSTRUMENTS_KEY = "tastytrade:instruments"
    ORDERS_KEY = "tastytrade:orders"                  # NEW
    COMPLEX_ORDERS_KEY = "tastytrade:complex-orders"  # NEW
```

### 4b: Add publish methods

```python
async def publish_order(self, order: PlacedOrder) -> None:
    """Write order to Redis HSET keyed by order ID."""
    await self.redis.hset(
        self.ORDERS_KEY,
        str(order.id),
        order.model_dump_json(by_alias=True),
    )
    await self.redis.publish(
        channel="tastytrade:events:Order",
        message=order.model_dump_json(by_alias=True),
    )
    logger.debug("Published order %d status=%s", order.id, order.status.value)

async def publish_complex_order(self, order: PlacedComplexOrder) -> None:
    """Write complex order to Redis HSET keyed by complex order ID."""
    await self.redis.hset(
        self.COMPLEX_ORDERS_KEY,
        str(order.id),
        order.model_dump_json(by_alias=True),
    )
    await self.redis.publish(
        channel="tastytrade:events:ComplexOrder",
        message=order.model_dump_json(by_alias=True),
    )
    logger.debug("Published complex order %d type=%s", order.id, order.type.value)
```

---

## Step 5: Add Consumer Coroutines

**File:** `src/tastytrade/accounts/orchestrator.py`

### 5a: Add consumer functions (after existing ones, line 53)

```python
async def _consume_orders(
    queue: asyncio.Queue,
    publisher: AccountStreamPublisher,
) -> None:
    """Drain Order events from the queue and publish to Redis."""
    while True:
        order = await queue.get()
        await publisher.publish_order(order)


async def _consume_complex_orders(
    queue: asyncio.Queue,
    publisher: AccountStreamPublisher,
) -> None:
    """Drain ComplexOrder events from the queue and publish to Redis."""
    while True:
        order = await queue.get()
        await publisher.publish_complex_order(order)
```

### 5b: Wire into run_account_stream_once (after line 185)

```python
# === Start consumer tasks for order + complex order queues ===
order_queue = streamer.queues[AccountEventType.ORDER]
complex_order_queue = streamer.queues[AccountEventType.COMPLEX_ORDER]

consumer_tasks.append(
    asyncio.create_task(
        _consume_orders(order_queue, publisher),
        name="order_consumer",
    )
)
consumer_tasks.append(
    asyncio.create_task(
        _consume_complex_orders(complex_order_queue, publisher),
        name="complex_order_consumer",
    )
)
```

No hydration needed for orders (unlike positions which REST-hydrate on connect). Orders are purely event-driven.

---

## Step 6: Unit Tests

**File:** `unit_tests/accounts/test_order_events.py` (new)

### Test Categories

1. **Model parsing** — PlacedOrder, PlacedComplexOrder, OrderLeg, OrderFill from sample JSON
2. **Enum coercion** — Unknown status/action/type values map to UNKNOWN
3. **Event routing** — `AccountStreamer.parse_event("Order", data)` returns `PlacedOrder`
4. **Event routing** — `AccountStreamer.parse_event("ComplexOrder", data)` returns `PlacedComplexOrder`
5. **Queue dispatch** — `_handle_event` puts parsed order into correct queue
6. **Publisher** — `publish_order` writes to correct Redis HSET key and pub/sub channel
7. **Publisher** — `publish_complex_order` writes to correct Redis HSET key and pub/sub channel

### Test Data

Use sample payloads from Step 0 as fixtures. If sandbox capture isn't done yet, use payloads from the community SDK test fixtures.

---

## Step 7: Functional Validation

1. Connect to sandbox, place a single-leg order → verify Order events flow through pipeline to Redis
2. Place a multi-leg order (spread) → verify ComplexOrder + individual Order events arrive
3. Cancel an order → verify Order event with `status: Cancelled` updates Redis
4. Verify `redis-cli HGETALL tastytrade:orders` shows order data
5. Verify `redis-cli HGETALL tastytrade:complex-orders` shows complex order data
6. Verify `redis-cli SUBSCRIBE tastytrade:events:Order` receives real-time events

---

## File Change Summary

| File | Change |
|---|---|
| `src/tastytrade/config/enumerations.py` | Add `ORDER`, `COMPLEX_ORDER` to `AccountEventType` |
| `src/tastytrade/accounts/models.py` | Add enums (OrderStatus, OrderAction, etc.), OrderFill, OrderLeg, PlacedOrder, PlacedComplexOrder |
| `src/tastytrade/accounts/streamer.py` | Update imports, queue type annotation, add branches in `parse_event()` |
| `src/tastytrade/accounts/publisher.py` | Add `ORDERS_KEY`, `COMPLEX_ORDERS_KEY`, `publish_order()`, `publish_complex_order()` |
| `src/tastytrade/accounts/orchestrator.py` | Add `_consume_orders()`, `_consume_complex_orders()`, wire into `run_account_stream_once()` |
| `unit_tests/accounts/test_order_events.py` | New test file for model parsing, routing, publishing |
| `docs/plans/TT-60-sample-payloads.json` | Sample payloads from sandbox (Step 0 output) |

---

## Execution Order

```
Step 0 → Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Step 6 → Step 7
 capture   enum    models   routing  publisher consumers  tests   validate
```

Steps 1–5 are code changes. Step 6 is tests. Step 7 is functional validation (PR evidence).
