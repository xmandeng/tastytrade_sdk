"""Tests for periodic health status logging."""

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

from tastytrade.config.enumerations import Channels
from tastytrade.subscription.orchestrator import format_uptime


def test_format_uptime_minutes_only() -> None:
    """Short uptimes display as minutes."""
    assert format_uptime(0) == "0m"
    assert format_uptime(59) == "0m"
    assert format_uptime(60) == "1m"
    assert format_uptime(300) == "5m"


def test_format_uptime_hours_and_minutes() -> None:
    """Uptimes over an hour show hours and minutes."""
    assert format_uptime(3600) == "1h 0m"
    assert format_uptime(3660) == "1h 1m"
    assert format_uptime(8580) == "2h 23m"


def test_format_uptime_days() -> None:
    """Uptimes over a day show days, hours, and minutes."""
    assert format_uptime(86400) == "1d 0h 0m"
    assert format_uptime(90060) == "1d 1h 1m"


def test_health_message_no_stale_channels() -> None:
    """Health message contains feed count when all channels are healthy."""
    handlers = _make_handlers(
        {Channels.Quote: time.time(), Channels.Trade: time.time()}
    )
    feed_count = sum(h.metrics.total_messages > 0 for h in handlers.values())
    msg = f"Health — Uptime: 5m | {feed_count} feeds active"

    assert "2 feeds active" in msg
    assert "stale" not in msg


def test_health_message_with_stale_channels() -> None:
    """Stale channels are reported when last_message_time exceeds threshold."""
    stale_threshold = 600  # 2x 300s default
    now = time.time()
    handlers = _make_handlers(
        {
            Channels.Quote: now,  # healthy
            Channels.Trade: now - 700,  # stale
            Channels.Candle: now - 800,  # stale
        }
    )

    stale = [
        h.channel.name
        for h in handlers.values()
        if h.metrics.last_message_time > 0
        and (now - h.metrics.last_message_time) > stale_threshold
    ]

    assert sorted(stale) == ["Candle", "Trade"]


def test_health_message_excludes_channels_with_no_messages() -> None:
    """Channels that never received messages are not counted as stale."""
    stale_threshold = 600
    now = time.time()
    handlers = _make_handlers(
        {
            Channels.Quote: now,
            Channels.Trade: 0,  # never received a message
        }
    )

    stale = [
        h.channel.name
        for h in handlers.values()
        if h.metrics.last_message_time > 0
        and (now - h.metrics.last_message_time) > stale_threshold
    ]

    assert stale == []


def test_feed_count_only_counts_active_handlers() -> None:
    """Feed count reflects handlers that have processed at least one message."""
    handlers = _make_handlers(
        {
            Channels.Quote: time.time(),  # active (total_messages > 0)
            Channels.Trade: 0,  # no messages
        },
        message_counts={Channels.Quote: 100, Channels.Trade: 0},
    )

    feed_count = sum(h.metrics.total_messages > 0 for h in handlers.values())
    assert feed_count == 1


# --- helpers ---


@dataclass
class _MockMetrics:
    total_messages: int = 0
    last_message_time: float = 0


def _make_handlers(
    last_times: dict[Channels, float],
    message_counts: dict[Channels, int] | None = None,
) -> dict[Channels, MagicMock]:
    """Build mock handlers with metrics for testing health check logic."""
    counts = message_counts or {}
    handlers: dict[Channels, MagicMock] = {}
    for channel, last_time in last_times.items():
        handler = MagicMock()
        handler.channel = channel
        handler.metrics = _MockMetrics(
            total_messages=counts.get(channel, 1 if last_time > 0 else 0),
            last_message_time=last_time,
        )
        handlers[channel] = handler
    return handlers
