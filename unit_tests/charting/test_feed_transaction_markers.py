"""The chart feed drops dxFeed transaction bookkeeping before it reaches the browser."""

import json
from typing import Any, AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from tastytrade.charting.feed import ChartFeed

CANDLE = "market:CandleEvent:SPX{=5m}"


class FakePubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages

    async def subscribe(self, *channels: str) -> None:
        return None

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        for m in self.messages:
            yield m


def message(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "message", "channel": CANDLE, "data": json.dumps(payload)}


@pytest.mark.asyncio
async def test_listen_drops_transaction_markers() -> None:
    pubsub = FakePubSub(
        [
            message(
                {
                    "eventSymbol": "SPX{=5m}",
                    "time": "2026-09-10T14:45:00Z",
                    "eventFlags": 0,
                    "close": 7601.47,
                }
            ),
            message(
                {
                    "eventSymbol": "SPX{=5m}",
                    "time": "2026-09-10T14:45:00Z",
                    "eventFlags": 1,
                    "close": 7601.95,
                }
            ),
            message(
                {
                    "eventSymbol": "SPX{=5m}",
                    "time": "2038-01-19T03:14:08.023Z",
                    "eventFlags": 2,
                    "count": 0,
                    "close": None,
                }
            ),
            message(
                {
                    "eventSymbol": "SPX{=5m}",
                    "time": "2026-09-10T14:45:00Z",
                    "eventFlags": 0,
                    "close": 7600.73,
                }
            ),
        ]
    )
    config = MagicMock()
    config.get.return_value = "redis://localhost:6379"
    with patch("tastytrade.charting.feed.aioredis.from_url") as from_url:
        from_url.return_value.pubsub.return_value = pubsub
        feed = ChartFeed(config)
        seen = [
            data
            async for kind, data in feed.listen("SPX", "SPX{=5m}")
            if kind == "candle"
        ]

    assert [d["close"] for d in seen] == [7601.47, 7600.73]
