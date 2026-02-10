"""Tests for AccountStreamer WebSocket manager (TT-29)."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.accounts.models import AccountBalance, Position
from tastytrade.accounts.streamer import (
    HEARTBEAT_INTERVAL_SECONDS,
    STREAMER_URLS,
    AccountStreamer,
)
from tastytrade.config.enumerations import AccountEventType, ReconnectReason


# ---------------------------------------------------------------------------
# Helpers — factory functions for event payloads
# ---------------------------------------------------------------------------


def make_position_event(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": "AAPL",
        "instrument-type": "Equity",
        "quantity": "100.0",
        "quantity-direction": "Long",
    }
    base.update(overrides)
    return base


def make_balance_event(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "cash-balance": "25000.50",
        "net-liquidating-value": "50000.75",
    }
    base.update(overrides)
    return base


def fresh_streamer() -> AccountStreamer:
    """Create a fresh AccountStreamer with no singleton state."""
    AccountStreamer.instance = None
    streamer = AccountStreamer.__new__(AccountStreamer)
    streamer.credentials = None
    streamer.queues = {event_type: asyncio.Queue() for event_type in AccountEventType}
    streamer.reconnect_event = asyncio.Event()
    streamer.should_reconnect = True
    streamer.reconnect_reason = None
    streamer.request_id = 0
    streamer.websocket = None
    streamer.session = None
    streamer.listener_task = None
    streamer.keepalive_task = None
    streamer.initialized = True
    return streamer


# ---------------------------------------------------------------------------
# AC1: Streamer URL selection
# ---------------------------------------------------------------------------


def test_streamer_url_production() -> None:
    assert STREAMER_URLS[False] == "wss://streamer.tastyworks.com"


def test_streamer_url_sandbox() -> None:
    assert STREAMER_URLS[True] == "wss://streamer.cert.tastyworks.com"


# ---------------------------------------------------------------------------
# AC2: Connect message format
# ---------------------------------------------------------------------------


def test_connect_message_includes_account_and_token() -> None:
    from tastytrade.accounts.messages import StreamerConnectMessage

    msg = StreamerConnectMessage(
        value=["5WT00001"],
        auth_token="tok123",  # type: ignore[call-arg]
        request_id=1,  # type: ignore[call-arg]
    )
    raw = msg.model_dump(by_alias=True)
    assert raw["value"] == ["5WT00001"]
    assert raw["auth-token"] == "tok123"
    assert raw["action"] == "connect"


def test_connect_message_uses_raw_token_no_bearer() -> None:
    from tastytrade.accounts.messages import StreamerConnectMessage

    token = "r8ZvXYZ...session-token"
    msg = StreamerConnectMessage(
        value=["5WT00001"],
        auth_token=token,  # type: ignore[call-arg]
        request_id=1,  # type: ignore[call-arg]
    )
    raw = msg.model_dump(by_alias=True)
    assert not raw["auth-token"].startswith("Bearer")
    assert raw["auth-token"] == token


# ---------------------------------------------------------------------------
# AC3: Event routing
# ---------------------------------------------------------------------------


def test_handle_event_routes_position_to_position_queue() -> None:
    streamer = fresh_streamer()
    event_data = {
        "type": "CurrentPosition",
        "data": make_position_event(),
        "timestamp": 1234567890,
    }
    streamer._handle_event(event_data)
    assert not streamer.queues[AccountEventType.CURRENT_POSITION].empty()
    item = streamer.queues[AccountEventType.CURRENT_POSITION].get_nowait()
    assert isinstance(item, Position)
    assert item.symbol == "AAPL"


def test_handle_event_routes_balance_to_balance_queue() -> None:
    streamer = fresh_streamer()
    event_data = {
        "type": "AccountBalance",
        "data": make_balance_event(),
        "timestamp": 1234567890,
    }
    streamer._handle_event(event_data)
    assert not streamer.queues[AccountEventType.ACCOUNT_BALANCE].empty()
    item = streamer.queues[AccountEventType.ACCOUNT_BALANCE].get_nowait()
    assert isinstance(item, AccountBalance)
    assert item.cash_balance == 25000.5


def test_handle_event_unknown_type_logs_warning() -> None:
    streamer = fresh_streamer()
    event_data = {
        "type": "Order",
        "data": {"some": "data"},
    }
    # Should not raise, unknown types are logged and skipped
    streamer._handle_event(event_data)
    assert streamer.queues[AccountEventType.CURRENT_POSITION].empty()
    assert streamer.queues[AccountEventType.ACCOUNT_BALANCE].empty()


def test_handle_event_batch_results() -> None:
    """Verify that batched results in socket_listener would call _handle_event per item."""
    streamer = fresh_streamer()
    events = [
        {"type": "CurrentPosition", "data": make_position_event(symbol="AAPL")},
        {"type": "CurrentPosition", "data": make_position_event(symbol="SPY")},
        {
            "type": "AccountBalance",
            "data": make_balance_event(**{"cash-balance": "10000.00"}),
        },
    ]
    for event in events:
        streamer._handle_event(event)

    assert streamer.queues[AccountEventType.CURRENT_POSITION].qsize() == 2
    assert streamer.queues[AccountEventType.ACCOUNT_BALANCE].qsize() == 1


# ---------------------------------------------------------------------------
# AC4: Heartbeat configuration
# ---------------------------------------------------------------------------


def test_heartbeat_interval_is_20_seconds() -> None:
    assert HEARTBEAT_INTERVAL_SECONDS == 20


@pytest.mark.asyncio
async def test_keepalive_sends_heartbeat() -> None:
    streamer = fresh_streamer()

    mock_ws = AsyncMock()
    streamer.websocket = mock_ws

    mock_session = MagicMock()
    mock_session.session.headers = {"Authorization": "tok123"}
    streamer.session = mock_session

    # Run keepalive task and cancel after one heartbeat
    async def run_keepalive() -> None:
        task = asyncio.create_task(streamer.send_keepalives())
        await asyncio.sleep(0.05)  # Let it start
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with patch("tastytrade.accounts.streamer.HEARTBEAT_INTERVAL_SECONDS", 0.01):
        await run_keepalive()

    assert mock_ws.send.called
    sent_json = mock_ws.send.call_args[0][0]
    sent_data = json.loads(sent_json)
    assert sent_data["action"] == "heartbeat"
    assert sent_data["auth-token"] == "tok123"


# ---------------------------------------------------------------------------
# AC5: Singleton pattern
# ---------------------------------------------------------------------------


def test_singleton_returns_same_instance() -> None:
    AccountStreamer.instance = None
    a = AccountStreamer.__new__(AccountStreamer)
    AccountStreamer.instance = a
    b = AccountStreamer.__new__(AccountStreamer)
    assert a is b
    AccountStreamer.instance = None  # cleanup


def test_singleton_init_guard_runs_once() -> None:
    AccountStreamer.instance = None
    s = AccountStreamer.__new__(AccountStreamer)
    s.__init__()  # type: ignore[misc]
    first_queues = s.queues
    s.__init__()  # type: ignore[misc]
    # Queues should be the same object — init guard prevented re-init
    assert s.queues is first_queues
    AccountStreamer.instance = None  # cleanup


# ---------------------------------------------------------------------------
# AC6: Reconnection signaling
# ---------------------------------------------------------------------------


def test_trigger_reconnect_sets_event() -> None:
    streamer = fresh_streamer()
    assert not streamer.reconnect_event.is_set()
    streamer.trigger_reconnect(ReconnectReason.CONNECTION_DROPPED)
    assert streamer.reconnect_event.is_set()
    assert streamer.reconnect_reason == ReconnectReason.CONNECTION_DROPPED


@pytest.mark.asyncio
async def test_wait_for_reconnect_signal_blocks_then_returns() -> None:
    streamer = fresh_streamer()

    async def trigger_later() -> None:
        await asyncio.sleep(0.01)
        streamer.trigger_reconnect(ReconnectReason.AUTH_EXPIRED)

    asyncio.create_task(trigger_later())
    reason = await asyncio.wait_for(streamer.wait_for_reconnect_signal(), timeout=1.0)
    assert reason == ReconnectReason.AUTH_EXPIRED


@pytest.mark.asyncio
async def test_wait_clears_event_after_signal() -> None:
    streamer = fresh_streamer()
    streamer.trigger_reconnect(ReconnectReason.TIMEOUT)
    await streamer.wait_for_reconnect_signal()
    assert not streamer.reconnect_event.is_set()


# ---------------------------------------------------------------------------
# AC8: Context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager_calls_close() -> None:
    streamer = fresh_streamer()
    streamer.close = AsyncMock()  # type: ignore[method-assign]
    async with streamer:
        pass
    streamer.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# parse_event
# ---------------------------------------------------------------------------


def test_parse_event_position() -> None:
    result = AccountStreamer.parse_event("CurrentPosition", make_position_event())
    assert isinstance(result, Position)
    assert result.symbol == "AAPL"


def test_parse_event_balance() -> None:
    result = AccountStreamer.parse_event("AccountBalance", make_balance_event())
    assert isinstance(result, AccountBalance)
    assert result.cash_balance == 25000.5


def test_parse_event_invalid_data_returns_none() -> None:
    result = AccountStreamer.parse_event("CurrentPosition", {"bad": "data"})
    assert result is None


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hydrate_enqueues_positions_and_balance() -> None:
    streamer = fresh_streamer()

    mock_client = AsyncMock()
    mock_client.get_positions.return_value = [
        Position.model_validate(make_position_event(symbol="AAPL")),
        Position.model_validate(make_position_event(symbol="SPY")),
    ]
    mock_client.get_balances.return_value = AccountBalance.model_validate(
        make_balance_event()
    )

    await streamer.hydrate(mock_client, "5WT00001")

    assert streamer.queues[AccountEventType.CURRENT_POSITION].qsize() == 2
    assert streamer.queues[AccountEventType.ACCOUNT_BALANCE].qsize() == 1


# ---------------------------------------------------------------------------
# AccountEventType enum
# ---------------------------------------------------------------------------


def test_account_event_type_values() -> None:
    assert AccountEventType.CURRENT_POSITION.value == "CurrentPosition"
    assert AccountEventType.ACCOUNT_BALANCE.value == "AccountBalance"
