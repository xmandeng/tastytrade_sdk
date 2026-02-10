"""Tests for Account Streamer protocol models (TT-29)."""

import pytest
from pydantic import ValidationError

from tastytrade.accounts.messages import (
    StreamerConnectMessage,
    StreamerEventEnvelope,
    StreamerHeartbeatMessage,
    StreamerResponse,
)


# ---------------------------------------------------------------------------
# StreamerConnectMessage
# ---------------------------------------------------------------------------


def test_connect_message_serializes_with_hyphenated_keys() -> None:
    msg = StreamerConnectMessage(
        value=["5WT00001"],
        auth_token="tok123",
        request_id=1,
    )
    raw = msg.model_dump(by_alias=True)
    assert raw["action"] == "connect"
    assert raw["auth-token"] == "tok123"
    assert raw["request-id"] == 1
    assert raw["value"] == ["5WT00001"]


def test_connect_message_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        StreamerConnectMessage(
            value=["5WT00001"],
            auth_token="tok123",
            request_id=1,
            bogus="oops",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# StreamerHeartbeatMessage
# ---------------------------------------------------------------------------


def test_heartbeat_message_serializes_with_hyphenated_keys() -> None:
    msg = StreamerHeartbeatMessage(
        auth_token="tok123",
        request_id=2,
    )
    raw = msg.model_dump(by_alias=True)
    assert raw["action"] == "heartbeat"
    assert raw["auth-token"] == "tok123"
    assert raw["request-id"] == 2


# ---------------------------------------------------------------------------
# StreamerResponse
# ---------------------------------------------------------------------------


def test_response_parses_ok_status() -> None:
    data = {
        "status": "ok",
        "action": "connect",
        "web-socket-session-id": "abc123",
        "request-id": 1,
    }
    resp = StreamerResponse.model_validate(data)
    assert resp.status == "ok"
    assert resp.action == "connect"
    assert resp.web_socket_session_id == "abc123"
    assert resp.request_id == 1


def test_response_parses_error_status() -> None:
    data = {
        "status": "error",
        "action": "connect",
        "web-socket-session-id": "abc123",
        "message": "failed",
    }
    resp = StreamerResponse.model_validate(data)
    assert resp.status == "error"
    assert resp.message == "failed"


def test_response_allows_extra_fields() -> None:
    data = {
        "status": "ok",
        "action": "heartbeat",
        "web-socket-session-id": "abc123",
        "new-server-field": "surprise",
    }
    resp = StreamerResponse.model_validate(data)
    assert resp.status == "ok"


# ---------------------------------------------------------------------------
# StreamerEventEnvelope
# ---------------------------------------------------------------------------


def test_event_envelope_parses_position_event() -> None:
    data = {
        "type": "CurrentPosition",
        "data": {
            "account-number": "5WT00001",
            "symbol": "AAPL",
            "quantity": "100",
        },
        "timestamp": 1688595114405,
        "ws-sequence": 42,
    }
    env = StreamerEventEnvelope.model_validate(data)
    assert env.type == "CurrentPosition"
    assert env.data["symbol"] == "AAPL"
    assert env.timestamp == 1688595114405
    assert env.ws_sequence == 42


def test_event_envelope_parses_balance_event() -> None:
    data = {
        "type": "AccountBalance",
        "data": {
            "account-number": "5WT00001",
            "cash-balance": "25000.50",
        },
        "timestamp": 1688595114500,
    }
    env = StreamerEventEnvelope.model_validate(data)
    assert env.type == "AccountBalance"
    assert env.data["cash-balance"] == "25000.50"


def test_event_envelope_allows_extra_fields() -> None:
    data = {
        "type": "CurrentPosition",
        "data": {"account-number": "5WT00001"},
        "extra-server-field": True,
    }
    env = StreamerEventEnvelope.model_validate(data)
    assert env.type == "CurrentPosition"


def test_event_envelope_optional_fields() -> None:
    data = {
        "type": "AccountBalance",
        "data": {"account-number": "5WT00001"},
    }
    env = StreamerEventEnvelope.model_validate(data)
    assert env.timestamp is None
    assert env.ws_sequence is None
