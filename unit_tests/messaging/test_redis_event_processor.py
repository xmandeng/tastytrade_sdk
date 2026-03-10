"""Tests for RedisEventProcessor pub/sub + HSET storage."""

from unittest.mock import AsyncMock

import pytest

from tastytrade.messaging.models.events import GreeksEvent, QuoteEvent
from tastytrade.messaging.processors.redis import RedisEventProcessor


def make_redis_processor() -> RedisEventProcessor:
    """Create a RedisEventProcessor with a mocked async Redis client."""
    processor = RedisEventProcessor.__new__(RedisEventProcessor)
    processor.redis = AsyncMock()  # type: ignore[assignment]
    processor.pl = __import__("polars").DataFrame()
    processor.frames = {}
    return processor


@pytest.mark.asyncio
async def test_process_event_publishes_to_channel() -> None:
    processor = make_redis_processor()
    event = QuoteEvent(
        eventSymbol="SPY", bidPrice=600.0, askPrice=601.0, bidSize=100.0, askSize=200.0
    )
    await processor.process_event(event)
    processor.redis.publish.assert_called_once()  # type: ignore[attr-defined]
    channel = processor.redis.publish.call_args[1]["channel"]  # type: ignore[attr-defined]
    assert channel == "market:QuoteEvent:SPY"


@pytest.mark.asyncio
async def test_process_event_stores_latest_in_hset() -> None:
    processor = make_redis_processor()
    event = QuoteEvent(
        eventSymbol="SPY", bidPrice=600.0, askPrice=601.0, bidSize=100.0, askSize=200.0
    )
    await processor.process_event(event)
    processor.redis.hset.assert_called_once()  # type: ignore[attr-defined]
    args = processor.redis.hset.call_args  # type: ignore[attr-defined]
    assert args[0][0] == "tastytrade:latest:QuoteEvent"
    assert args[0][1] == "SPY"


@pytest.mark.asyncio
async def test_process_event_stores_greeks_in_hset() -> None:
    processor = make_redis_processor()
    event = GreeksEvent(
        eventSymbol=".SPY260402P666",
        delta=-0.24,
        gamma=0.01,
        theta=-0.18,
        vega=0.68,
        rho=-0.17,
        volatility=0.19,
    )
    await processor.process_event(event)
    processor.redis.hset.assert_called_once()  # type: ignore[attr-defined]
    args = processor.redis.hset.call_args  # type: ignore[attr-defined]
    assert args[0][0] == "tastytrade:latest:GreeksEvent"


@pytest.mark.asyncio
async def test_process_event_latest_overwrites_previous() -> None:
    processor = make_redis_processor()
    event1 = QuoteEvent(
        eventSymbol="SPY", bidPrice=600.0, askPrice=601.0, bidSize=100.0, askSize=200.0
    )
    event2 = QuoteEvent(
        eventSymbol="SPY", bidPrice=605.0, askPrice=606.0, bidSize=100.0, askSize=200.0
    )
    await processor.process_event(event1)
    await processor.process_event(event2)
    # HSET called twice for same key — last value wins in Redis
    assert processor.redis.hset.call_count == 2  # type: ignore[attr-defined]
    last_call = processor.redis.hset.call_args  # type: ignore[attr-defined]
    assert "605.0" in last_call[0][2] or "605" in last_call[0][2]
