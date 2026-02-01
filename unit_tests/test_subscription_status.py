"""Tests for subscription status query and formatting."""

import json
from datetime import datetime, timedelta, timezone

from tastytrade.subscription.status import (
    StatusResult,
    SubscriptionInfo,
    _parse_subscription,
    format_status,
)


# --- SubscriptionInfo ---


def test_candle_feed_type() -> None:
    sub = SubscriptionInfo(symbol="AAPL{=d}", active=True, last_update=None)
    assert sub.feed_type == "Candle"


def test_ticker_feed_type() -> None:
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=None)
    assert sub.feed_type == "Ticker"


def test_age_seconds_none_when_no_update() -> None:
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=None)
    assert sub.age_seconds is None


def test_age_seconds_computed() -> None:
    recent = datetime.now(timezone.utc) - timedelta(seconds=30)
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=recent)
    assert sub.age_seconds is not None
    assert 29 <= sub.age_seconds <= 32


def test_age_display_seconds() -> None:
    recent = datetime.now(timezone.utc) - timedelta(seconds=10)
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=recent)
    assert sub.age_display.endswith("s ago")


def test_age_display_minutes() -> None:
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=recent)
    assert sub.age_display.endswith("m ago")


def test_age_display_hours() -> None:
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=recent)
    assert sub.age_display.endswith("h ago")


def test_age_display_days() -> None:
    recent = datetime.now(timezone.utc) - timedelta(days=3)
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=recent)
    assert sub.age_display.endswith("d ago")


def test_age_display_unknown() -> None:
    sub = SubscriptionInfo(symbol="AAPL", active=True, last_update=None)
    assert sub.age_display == "unknown"


# --- _parse_subscription ---


def test_parse_active_subscription() -> None:
    raw = {
        "active": True,
        "last_update": "2026-02-01T12:00:00+00:00",
        "metadata": {"price": 150.0},
    }
    sub = _parse_subscription("AAPL", raw)
    assert sub.symbol == "AAPL"
    assert sub.active is True
    assert sub.last_update is not None
    assert sub.metadata == {"price": 150.0}


def test_parse_inactive_subscription() -> None:
    raw: dict[str, object] = {"active": False, "last_update": None, "metadata": {}}
    sub = _parse_subscription("SPY", raw)
    assert sub.active is False
    assert sub.last_update is None


def test_parse_missing_fields() -> None:
    raw: dict[str, object] = {}
    sub = _parse_subscription("QQQ", raw)
    assert sub.active is False
    assert sub.last_update is None
    assert sub.metadata == {}


def test_parse_invalid_timestamp() -> None:
    raw: dict[str, object] = {
        "active": True,
        "last_update": "not-a-date",
        "metadata": {},
    }
    sub = _parse_subscription("AAPL", raw)
    assert sub.last_update is None


# --- StatusResult ---


def test_active_subscriptions_filter() -> None:
    result = StatusResult(
        redis_connected=True,
        subscriptions=[
            SubscriptionInfo(symbol="AAPL", active=True, last_update=None),
            SubscriptionInfo(symbol="SPY", active=False, last_update=None),
        ],
    )
    assert len(result.active_subscriptions) == 1
    assert result.active_subscriptions[0].symbol == "AAPL"


def test_candle_and_ticker_split() -> None:
    result = StatusResult(
        redis_connected=True,
        subscriptions=[
            SubscriptionInfo(symbol="AAPL", active=True, last_update=None),
            SubscriptionInfo(symbol="AAPL{=d}", active=True, last_update=None),
            SubscriptionInfo(symbol="SPY{=5m}", active=True, last_update=None),
        ],
    )
    assert len(result.ticker_subscriptions) == 1
    assert len(result.candle_subscriptions) == 2


# --- format_status (table) ---


def test_disconnected_shows_error() -> None:
    result = StatusResult(
        redis_connected=False,
        error="Cannot connect to Redis at redis:6379 — Connection refused",
    )
    output = format_status(result)
    assert "Disconnected" in output
    assert "Cannot connect" in output


def test_no_active_subscriptions() -> None:
    result = StatusResult(redis_connected=True, redis_version="7.0.0")
    output = format_status(result)
    assert "No active subscriptions" in output
    assert "Connected" in output


def test_active_subscriptions_displayed() -> None:
    recent = datetime.now(timezone.utc) - timedelta(seconds=5)
    result = StatusResult(
        redis_connected=True,
        redis_version="7.0.0",
        subscriptions=[
            SubscriptionInfo(symbol="AAPL", active=True, last_update=recent),
            SubscriptionInfo(symbol="AAPL{=d}", active=True, last_update=recent),
        ],
    )
    output = format_status(result)
    assert "Active Subscriptions: 2" in output
    assert "Ticker feeds: 1" in output
    assert "Candle feeds: 1" in output
    assert "AAPL" in output
    assert "AAPL{=d}" in output


def test_connected_shows_version() -> None:
    result = StatusResult(redis_connected=True, redis_version="7.2.4")
    output = format_status(result)
    assert "v7.2.4" in output


# --- format_status (JSON) ---


def test_json_structure() -> None:
    recent = datetime.now(timezone.utc) - timedelta(seconds=5)
    result = StatusResult(
        redis_connected=True,
        redis_version="7.0.0",
        subscriptions=[
            SubscriptionInfo(symbol="AAPL", active=True, last_update=recent),
            SubscriptionInfo(symbol="AAPL{=d}", active=True, last_update=recent),
        ],
    )
    output = format_status(result, as_json=True)
    data = json.loads(output)
    assert data["redis"]["connected"] is True
    assert data["subscriptions"]["active"] == 2
    assert len(data["subscriptions"]["ticker"]) == 1
    assert len(data["subscriptions"]["candle"]) == 1


def test_json_includes_error() -> None:
    result = StatusResult(redis_connected=False, error="Connection refused")
    output = format_status(result, as_json=True)
    data = json.loads(output)
    assert data["error"] == "Connection refused"


def test_json_no_error_key_when_connected() -> None:
    result = StatusResult(redis_connected=True, redis_version="7.0.0")
    output = format_status(result, as_json=True)
    data = json.loads(output)
    assert "error" not in data
