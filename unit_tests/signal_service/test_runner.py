"""Tests for the EngineRunner generic harness."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.messaging.models.events import CandleEvent
from tastytrade.signal.runner import EngineRunner


@pytest.fixture
def runner() -> EngineRunner:
    """Create an EngineRunner with mocked dependencies (including publisher)."""
    return EngineRunner(
        name="test_engine",
        subscription=AsyncMock(),
        channels=["market:CandleEvent:SPX{=5m}"],
        event_type=CandleEvent,
        on_event=MagicMock(),
        publisher=MagicMock(),
    )


@pytest.fixture
def sink_runner() -> EngineRunner:
    """Create an EngineRunner without publisher (persistence / sink mode)."""
    return EngineRunner(
        name="test_sink",
        subscription=AsyncMock(),
        channels=["market:TradeSignal:*"],
        event_type=CandleEvent,
        on_event=MagicMock(),
    )


def test_runner_stores_config(runner: EngineRunner) -> None:
    assert runner.name == "test_engine"
    assert runner.channels == ["market:CandleEvent:SPX{=5m}"]
    assert runner.event_type is CandleEvent


def test_runner_publisher_is_optional(sink_runner: EngineRunner) -> None:
    """EngineRunner works without a publisher (sink mode)."""
    assert sink_runner.publisher is None
    assert sink_runner.name == "test_sink"
    assert sink_runner.channels == ["market:TradeSignal:*"]


@pytest.mark.asyncio
async def test_runner_start_connects_and_subscribes(runner: EngineRunner) -> None:
    """start() should connect subscription and subscribe with on_event callback."""
    with patch("tastytrade.signal.runner.asyncio.Event") as mock_event_cls:
        mock_event = MagicMock()
        mock_event.wait = AsyncMock(side_effect=asyncio.CancelledError)
        mock_event_cls.return_value = mock_event

        await runner.start()

    runner.subscription.connect.assert_awaited_once()  # type: ignore[attr-defined]
    runner.subscription.subscribe.assert_awaited_once_with(  # type: ignore[attr-defined]
        "market:CandleEvent:SPX{=5m}",
        event_type=CandleEvent,
        on_update=runner.on_event,
    )


@pytest.mark.asyncio
async def test_runner_start_subscribes_multiple_channels() -> None:
    """start() should subscribe to all channels."""
    channels = [
        "market:CandleEvent:SPX{=5m}",
        "market:CandleEvent:SPX{=15m}",
    ]
    runner = EngineRunner(
        name="multi",
        subscription=AsyncMock(),
        channels=channels,
        event_type=CandleEvent,
        on_event=MagicMock(),
        publisher=MagicMock(),
    )

    with patch("tastytrade.signal.runner.asyncio.Event") as mock_event_cls:
        mock_event = MagicMock()
        mock_event.wait = AsyncMock(side_effect=asyncio.CancelledError)
        mock_event_cls.return_value = mock_event

        await runner.start()

    assert runner.subscription.subscribe.await_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_runner_stop_closes_publisher_and_subscription(
    runner: EngineRunner,
) -> None:
    """stop() should close publisher and subscription."""
    await runner.stop()

    runner.publisher.close.assert_called_once()  # type: ignore[union-attr]
    runner.subscription.close.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_runner_stop_without_publisher(sink_runner: EngineRunner) -> None:
    """stop() should work without publisher (no error)."""
    await sink_runner.stop()

    # Publisher is None — no close() call to assert
    assert sink_runner.publisher is None
    sink_runner.subscription.close.assert_awaited_once()  # type: ignore[attr-defined]
