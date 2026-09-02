"""TT-157: warn when published candles trail wall clock (pipeline backlog)."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.messaging.models.events import CandleEvent, QuoteEvent
from tastytrade.messaging.processors.redis import RedisEventProcessor


def make_processor() -> RedisEventProcessor:
    p = RedisEventProcessor.__new__(RedisEventProcessor)
    # TT-164 phase 2: commands go through one pipelined round-trip.
    p.redis = MagicMock()  # type: ignore[assignment]
    p.redis.pipeline.return_value.execute = AsyncMock(return_value=[])
    p.last_lag_warning = 0.0
    return p


def candle(symbol: str, minutes_old: float) -> CandleEvent:
    return CandleEvent(
        eventSymbol=symbol,
        time=datetime.now(timezone.utc) - timedelta(minutes=minutes_old),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
    )


@pytest.mark.asyncio
async def test_fresh_candle_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    p = make_processor()
    with caplog.at_level(logging.WARNING):
        await p.process_event(candle("SPX{=5m}", minutes_old=2))
    assert "Candle publish lag" not in caplog.text


@pytest.mark.asyncio
async def test_stale_candle_warns(caplog: pytest.LogCaptureFixture) -> None:
    p = make_processor()
    with caplog.at_level(logging.WARNING):
        await p.process_event(candle("SPX{=5m}", minutes_old=45))
    assert "Candle publish lag" in caplog.text
    assert "SPX{=5m}" in caplog.text


@pytest.mark.asyncio
async def test_warning_rate_limited(caplog: pytest.LogCaptureFixture) -> None:
    p = make_processor()
    with caplog.at_level(logging.WARNING):
        await p.process_event(candle("SPX{=5m}", minutes_old=45))
        await p.process_event(candle("SPX{=5m}", minutes_old=46))
    assert caplog.text.count("Candle publish lag") == 1


@pytest.mark.asyncio
async def test_threshold_scales_with_interval(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A forming daily bar is legitimately many hours old — never warn.
    p = make_processor()
    with caplog.at_level(logging.WARNING):
        await p.process_event(candle("SPX{=1d}", minutes_old=600))
    assert "Candle publish lag" not in caplog.text


@pytest.mark.asyncio
async def test_non_candle_events_ignored(caplog: pytest.LogCaptureFixture) -> None:
    p = make_processor()
    event = QuoteEvent(
        eventSymbol="SPY", bidPrice=1.0, askPrice=2.0, bidSize=1.0, askSize=1.0
    )
    with caplog.at_level(logging.WARNING):
        await p.process_event(event)
    assert "Candle publish lag" not in caplog.text
    p.redis.pipeline.return_value.publish.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_stale_candle_still_published(caplog: pytest.LogCaptureFixture) -> None:
    # The warning observes; it must never block the pipeline.
    p = make_processor()
    with caplog.at_level(logging.WARNING):
        await p.process_event(candle("SPX{=m}", minutes_old=120))
    p.redis.pipeline.return_value.publish.assert_called_once()  # type: ignore[attr-defined]
    p.redis.pipeline.return_value.hset.assert_called_once()  # type: ignore[attr-defined]
