"""Tests for Order & ComplexOrder event pipeline (TT-60).

Covers model parsing, enum coercion, event routing, queue dispatch, and publisher methods.
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tastytrade.accounts.models import (
    ComplexOrderType,
    OrderAction,
    OrderFill,
    OrderLeg,
    OrderStatus,
    OrderType,
    PlacedComplexOrder,
    PlacedOrder,
    PriceEffect,
    TimeInForce,
)
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.accounts.streamer import AccountStreamer
from tastytrade.config.enumerations import AccountEventType


# ---------------------------------------------------------------------------
# Factory functions — hyphenated keys matching wire protocol
# ---------------------------------------------------------------------------


def make_fill_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fill-id": "fill-001",
        "quantity": "1.0",
        "fill-price": "185.50",
        "filled-at": "2026-03-02T14:30:00Z",
        "destination-venue": "CBOE",
        "ext-exec-id": "ext-001",
        "ext-group-fill-id": "grp-001",
    }
    base.update(overrides)
    return base


def make_leg_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instrument-type": "Equity Option",
        "symbol": "AAPL  260320C00185000",
        "action": "Buy to Open",
        "quantity": "1.0",
        "remaining-quantity": "0.0",
        "fills": [make_fill_data()],
    }
    base.update(overrides)
    return base


def make_order_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 12345,
        "account-number": "5WT00001",
        "order-type": "Limit",
        "time-in-force": "Day",
        "price": "2.50",
        "price-effect": "Debit",
        "size": 1,
        "status": "Filled",
        "cancellable": False,
        "editable": False,
        "underlying-symbol": "AAPL",
        "underlying-instrument-type": "Equity",
        "legs": [make_leg_data()],
        "received-at": "2026-03-02T14:00:00Z",
        "updated-at": "2026-03-02T14:30:00Z",
        "terminal-at": "2026-03-02T14:30:00Z",
    }
    base.update(overrides)
    return base


def make_complex_order_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 99001,
        "account-number": "5WT00001",
        "type": "OCO",
        "orders": [
            make_order_data(id=12345, status="Filled"),
            make_order_data(id=12346, status="Cancelled"),
        ],
        "terminal-at": "2026-03-02T15:00:00Z",
    }
    base.update(overrides)
    return base


def fresh_streamer() -> AccountStreamer:
    """Create a fresh AccountStreamer with no singleton state."""
    AccountStreamer.instance = None
    streamer = AccountStreamer.__new__(AccountStreamer)
    streamer.credentials = None
    streamer.queues = {event_type: asyncio.Queue() for event_type in AccountEventType}
    streamer.reconnect_signal = None
    streamer.request_id = 0
    streamer.websocket = None
    streamer.session = None
    streamer.listener_task = None
    streamer.keepalive_task = None
    streamer.initialized = True
    return streamer


# ---------------------------------------------------------------------------
# 1. Model parsing — OrderFill
# ---------------------------------------------------------------------------


def test_order_fill_parses_hyphenated_json() -> None:
    fill = OrderFill.model_validate(make_fill_data())
    assert fill.fill_id == "fill-001"
    assert fill.quantity == 1.0
    assert fill.fill_price == 185.50
    assert fill.destination_venue == "CBOE"


def test_order_fill_float_coercion() -> None:
    fill = OrderFill.model_validate(make_fill_data(quantity="5.0"))
    assert fill.quantity == 5.0
    assert isinstance(fill.quantity, float)


def test_order_fill_optional_fields() -> None:
    data = make_fill_data()
    del data["destination-venue"]
    del data["ext-exec-id"]
    del data["ext-group-fill-id"]
    fill = OrderFill.model_validate(data)
    assert fill.destination_venue is None
    assert fill.ext_exec_id is None


# ---------------------------------------------------------------------------
# 2. Model parsing — OrderLeg
# ---------------------------------------------------------------------------


def test_order_leg_parses_with_fills() -> None:
    leg = OrderLeg.model_validate(make_leg_data())
    assert leg.symbol == "AAPL  260320C00185000"
    assert leg.action == OrderAction.BUY_TO_OPEN
    assert leg.quantity == 1.0
    assert len(leg.fills) == 1
    assert leg.fills[0].fill_id == "fill-001"


def test_order_leg_empty_fills() -> None:
    leg = OrderLeg.model_validate(make_leg_data(fills=[]))
    assert leg.fills == []


# ---------------------------------------------------------------------------
# 3. Model parsing — PlacedOrder
# ---------------------------------------------------------------------------


def test_placed_order_parses_full_payload() -> None:
    order = PlacedOrder.model_validate(make_order_data())
    assert order.id == 12345
    assert order.account_number == "5WT00001"
    assert order.order_type == OrderType.LIMIT
    assert order.time_in_force == TimeInForce.DAY
    assert order.price == 2.50
    assert order.price_effect == PriceEffect.DEBIT
    assert order.status == OrderStatus.FILLED
    assert order.underlying_symbol == "AAPL"
    assert len(order.legs) == 1


def test_placed_order_is_frozen() -> None:
    order = PlacedOrder.model_validate(make_order_data())
    with pytest.raises(ValidationError):
        order.status = OrderStatus.CANCELLED  # type: ignore[misc]


def test_placed_order_preserves_extra_fields() -> None:
    """extra='allow' preserves unknown brokerage fields on model_extra."""
    data = make_order_data()
    data["unexpected-field"] = "preserved"
    order = PlacedOrder.model_validate(data)
    assert order.id == 12345
    assert order.model_extra is not None
    assert order.model_extra["unexpected-field"] == "preserved"


def test_placed_order_optional_timestamps() -> None:
    data = make_order_data()
    del data["terminal-at"]
    order = PlacedOrder.model_validate(data)
    assert order.terminal_at is None


# ---------------------------------------------------------------------------
# 4. Model parsing — PlacedComplexOrder
# ---------------------------------------------------------------------------


def test_placed_complex_order_parses_full_payload() -> None:
    order = PlacedComplexOrder.model_validate(make_complex_order_data())
    assert order.id == 99001
    assert order.account_number == "5WT00001"
    assert order.type == ComplexOrderType.OCO
    assert len(order.orders) == 2
    assert order.orders[0].id == 12345
    assert order.orders[1].status == OrderStatus.CANCELLED


def test_placed_complex_order_ignores_extra_fields() -> None:
    data = make_complex_order_data()
    data["unknown-field"] = "ignored"
    order = PlacedComplexOrder.model_validate(data)
    assert order.id == 99001


def test_placed_complex_order_with_trigger() -> None:
    data = make_complex_order_data()
    data["trigger-order"] = make_order_data(id=12347, status="Live")
    order = PlacedComplexOrder.model_validate(data)
    assert order.trigger_order is not None
    assert order.trigger_order.id == 12347


# ---------------------------------------------------------------------------
# 5. Enum coercion — unknown values map to UNKNOWN
# ---------------------------------------------------------------------------


def test_unknown_order_status_coerces() -> None:
    order = PlacedOrder.model_validate(make_order_data(status="BrandNewStatus"))
    assert order.status == OrderStatus.UNKNOWN


def test_unknown_order_type_coerces() -> None:
    data = make_order_data()
    data["order-type"] = "TrailingStop"
    order = PlacedOrder.model_validate(data)
    assert order.order_type == OrderType.UNKNOWN


def test_unknown_time_in_force_coerces() -> None:
    data = make_order_data()
    data["time-in-force"] = "FOK"
    order = PlacedOrder.model_validate(data)
    assert order.time_in_force == TimeInForce.UNKNOWN


def test_unknown_order_action_coerces() -> None:
    leg = OrderLeg.model_validate(make_leg_data(action="Sell Short"))
    assert leg.action == OrderAction.UNKNOWN


def test_unknown_complex_order_type_coerces() -> None:
    data = make_complex_order_data()
    data["type"] = "BRACKET"
    order = PlacedComplexOrder.model_validate(data)
    assert order.type == ComplexOrderType.UNKNOWN


# ---------------------------------------------------------------------------
# 6. Event routing — AccountStreamer.parse_event
# ---------------------------------------------------------------------------


def test_parse_event_order_returns_placed_order() -> None:
    result = AccountStreamer.parse_event("Order", make_order_data())
    assert isinstance(result, PlacedOrder)
    assert result.id == 12345


def test_parse_event_complex_order_returns_placed_complex_order() -> None:
    result = AccountStreamer.parse_event("ComplexOrder", make_complex_order_data())
    assert isinstance(result, PlacedComplexOrder)
    assert result.id == 99001


def test_parse_event_order_invalid_data_returns_none() -> None:
    result = AccountStreamer.parse_event("Order", {"bad": "data"})
    assert result is None


def test_parse_event_complex_order_invalid_data_returns_none() -> None:
    result = AccountStreamer.parse_event("ComplexOrder", {"bad": "data"})
    assert result is None


# ---------------------------------------------------------------------------
# 7. Queue dispatch — handle_event routes to correct queue
# ---------------------------------------------------------------------------


def testhandle_event_routes_order_to_order_queue() -> None:
    streamer = fresh_streamer()
    event_data = {
        "type": "Order",
        "data": make_order_data(),
        "timestamp": 1234567890,
    }
    streamer.handle_event(event_data)
    assert not streamer.queues[AccountEventType.ORDER].empty()
    item = streamer.queues[AccountEventType.ORDER].get_nowait()
    assert isinstance(item, PlacedOrder)
    assert item.id == 12345


def testhandle_event_routes_complex_order_to_complex_order_queue() -> None:
    streamer = fresh_streamer()
    event_data = {
        "type": "ComplexOrder",
        "data": make_complex_order_data(),
        "timestamp": 1234567890,
    }
    streamer.handle_event(event_data)
    assert not streamer.queues[AccountEventType.COMPLEX_ORDER].empty()
    item = streamer.queues[AccountEventType.COMPLEX_ORDER].get_nowait()
    assert isinstance(item, PlacedComplexOrder)
    assert item.id == 99001


def testhandle_event_order_does_not_affect_other_queues() -> None:
    streamer = fresh_streamer()
    event_data = {
        "type": "Order",
        "data": make_order_data(),
        "timestamp": 1234567890,
    }
    streamer.handle_event(event_data)
    assert streamer.queues[AccountEventType.CURRENT_POSITION].empty()
    assert streamer.queues[AccountEventType.ACCOUNT_BALANCE].empty()
    assert streamer.queues[AccountEventType.COMPLEX_ORDER].empty()


# ---------------------------------------------------------------------------
# 8. AccountEventType enum values
# ---------------------------------------------------------------------------


def test_account_event_type_order_value() -> None:
    assert AccountEventType.ORDER.value == "Order"


def test_account_event_type_complex_order_value() -> None:
    assert AccountEventType.COMPLEX_ORDER.value == "ComplexOrder"


def test_account_event_type_lookup_from_wire_name() -> None:
    assert AccountEventType("Order") == AccountEventType.ORDER
    assert AccountEventType("ComplexOrder") == AccountEventType.COMPLEX_ORDER


# ---------------------------------------------------------------------------
# 9. Publisher — Redis key constants
# ---------------------------------------------------------------------------


def test_orders_redis_key() -> None:
    assert AccountStreamPublisher.ORDERS_KEY == "tastytrade:orders"


def test_complex_orders_redis_key() -> None:
    assert AccountStreamPublisher.COMPLEX_ORDERS_KEY == "tastytrade:complex-orders"


# ---------------------------------------------------------------------------
# 10. Publisher — publish_order
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def publisher(mock_redis: AsyncMock) -> AccountStreamPublisher:
    pub = AccountStreamPublisher.__new__(AccountStreamPublisher)
    pub.redis = mock_redis
    return pub


@pytest.mark.asyncio
async def test_publish_order_writes_hset(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    order = PlacedOrder.model_validate(make_order_data())
    await publisher.publish_order(order)
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "tastytrade:orders"
    assert call_args[0][1] == "12345"


@pytest.mark.asyncio
async def test_publish_order_publishes_pubsub(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    order = PlacedOrder.model_validate(make_order_data())
    await publisher.publish_order(order)
    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[1]["channel"]
    assert channel == "tastytrade:events:Order"


@pytest.mark.asyncio
async def test_publish_order_json_is_valid(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    order = PlacedOrder.model_validate(make_order_data())
    await publisher.publish_order(order)
    hset_json = mock_redis.hset.call_args[0][2]
    parsed = json.loads(hset_json)
    assert parsed["id"] == 12345
    assert parsed["status"] == "Filled"


# ---------------------------------------------------------------------------
# 11. Publisher — publish_complex_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_complex_order_writes_hset(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    order = PlacedComplexOrder.model_validate(make_complex_order_data())
    await publisher.publish_complex_order(order)
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "tastytrade:complex-orders"
    assert call_args[0][1] == "99001"


@pytest.mark.asyncio
async def test_publish_complex_order_publishes_pubsub(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    order = PlacedComplexOrder.model_validate(make_complex_order_data())
    await publisher.publish_complex_order(order)
    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[1]["channel"]
    assert channel == "tastytrade:events:ComplexOrder"


@pytest.mark.asyncio
async def test_publish_complex_order_json_is_valid(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    order = PlacedComplexOrder.model_validate(make_complex_order_data())
    await publisher.publish_complex_order(order)
    hset_json = mock_redis.hset.call_args[0][2]
    parsed = json.loads(hset_json)
    assert parsed["id"] == 99001
    assert parsed["type"] == "OCO"
    assert len(parsed["orders"]) == 2
