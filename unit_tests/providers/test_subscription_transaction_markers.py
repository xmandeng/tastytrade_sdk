"""The consumer-side feed drops dxFeed transaction bookkeeping.

dxFeed wraps candle corrections in a transaction: a TX_PENDING copy of the
forming bar, then a REMOVE_EVENT placeholder with no prices and a far-future
timestamp. Studies downstream compare timestamps to detect a new bar, so the
placeholder must never be delivered.
"""

import json
from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest

from tastytrade.messaging.models.events import CandleEvent
from tastytrade.providers.subscriptions import RedisSubscription

CHANNEL = "market:CandleEvent:SPX{=5m}"


def message(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "pmessage",
        "pattern": CHANNEL.encode(),
        "channel": CHANNEL.encode(),
        "data": json.dumps(payload).encode(),
    }


class FakePubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        for m in self.messages:
            yield m


@pytest.mark.asyncio
async def test_listener_drops_transaction_markers() -> None:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        "host": "localhost",
        "port": 6379,
        "db": 0,
    }.get(key, default)
    sub = RedisSubscription(config)
    received: list[CandleEvent] = []
    sub.subscriptions.add(CHANNEL)
    sub._event_types[CHANNEL] = CandleEvent
    sub._callbacks[CHANNEL] = lambda e: received.append(e)  # type: ignore[arg-type]
    sub.pubsub = FakePubSub(  # type: ignore[assignment]
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

    await sub.listener()

    assert [e.close for e in received] == [7601.47, 7600.73]
