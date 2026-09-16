"""The chart feed routes the implied-vol index's candle channel as "iv"."""

import json
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from tastytrade.charting.feed import ChartFeed


class FakePubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
        self.subscribed: list[str] = []

    async def subscribe(self, *channels: str) -> None:
        self.subscribed.extend(channels)

    async def listen(self) -> Any:
        for m in self.messages:
            yield m

    async def unsubscribe(self) -> None:
        pass

    async def close(self) -> None:
        pass


def feed_with(messages: list[dict[str, Any]]) -> tuple[ChartFeed, FakePubSub]:
    feed = ChartFeed.__new__(ChartFeed)
    pubsub = FakePubSub(messages)
    redis = MagicMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    feed.redis = redis
    feed.pubsub = None
    return feed, pubsub


def message(channel: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "message", "channel": channel, "data": json.dumps(payload)}


@pytest.mark.asyncio
async def test_implied_channel_is_subscribed_and_routed() -> None:
    feed, pubsub = feed_with(
        [
            message("market:CandleEvent:SPX{=5m}", {"close": 7600.0}),
            message("market:CandleEvent:VIX1D{=5m}", {"close": 15.3}),
            message("market:HorizontalLine:SPX", {"price": 7590.0}),
        ]
    )
    events = [e async for e in feed.listen("SPX", "SPX{=5m}", "VIX1D{=5m}")]
    assert pubsub.subscribed == [
        "market:CandleEvent:SPX{=5m}",
        "market:HorizontalLine:SPX",
        "market:CandleEvent:VIX1D{=5m}",
    ]
    assert [
        (kind, cast(dict[str, Any], data)["close" if kind != "level" else "price"])
        for kind, data in events
    ] == [
        ("candle", 7600.0),
        ("iv", 15.3),
        ("level", 7590.0),
    ]


@pytest.mark.asyncio
async def test_without_implied_symbol_only_two_channels() -> None:
    feed, pubsub = feed_with(
        [message("market:CandleEvent:VIX1D{=5m}", {"close": 15.3})]
    )
    events = [e async for e in feed.listen("SPX", "SPX{=5m}")]
    assert pubsub.subscribed == [
        "market:CandleEvent:SPX{=5m}",
        "market:HorizontalLine:SPX",
    ]
    assert events == []
