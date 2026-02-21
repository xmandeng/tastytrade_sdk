"""Tests for RedisSubscription on_update callback (event-driven mode)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.messaging.models.events import CandleEvent
from tastytrade.providers.subscriptions import RedisSubscription


@pytest.fixture
def subscription() -> RedisSubscription:
    """Create a RedisSubscription with mocked config."""
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        "host": "localhost",
        "port": 6379,
        "db": 0,
    }.get(key, default)
    return RedisSubscription(config)


def test_callback_stored_on_subscribe(subscription: RedisSubscription) -> None:
    """on_update callback should be stored per pattern."""
    callback = MagicMock()

    # Run subscribe (mock the async parts)
    with patch.object(subscription, "pubsub", create=True, new=AsyncMock()):
        with patch.object(subscription, "listener_task", create=True, new=None):
            with patch("asyncio.create_task") as mock_task:
                mock_task.return_value = MagicMock()
                asyncio.get_event_loop().run_until_complete(
                    subscription.subscribe(
                        "market:CandleEvent:SPX{=5m}",
                        event_type=CandleEvent,
                        on_update=callback,
                    )
                )

    assert subscription._callbacks["market:CandleEvent:SPX{=5m}"] is callback


def test_no_callback_means_empty_callbacks(subscription: RedisSubscription) -> None:
    """When no on_update is provided, _callbacks should remain empty."""
    with patch.object(subscription, "pubsub", create=True, new=AsyncMock()):
        with patch.object(subscription, "listener_task", create=True, new=None):
            with patch("asyncio.create_task") as mock_task:
                mock_task.return_value = MagicMock()
                asyncio.get_event_loop().run_until_complete(
                    subscription.subscribe(
                        "market:CandleEvent:SPX{=5m}",
                        event_type=CandleEvent,
                    )
                )

    assert "market:CandleEvent:SPX{=5m}" not in subscription._callbacks
