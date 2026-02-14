"""Tests for RedisPublisher and TradeSignal deserialization."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.messaging.models.events import QuoteEvent
from tastytrade.providers.subscriptions import RedisPublisher


def make_quote() -> QuoteEvent:
    return QuoteEvent(
        eventSymbol="SPY",
        bidPrice=500.0,
        askPrice=501.0,
        bidSize=100.0,
        askSize=100.0,
    )


def make_trade_signal() -> TradeSignal:
    return TradeSignal(
        eventSymbol="SPX{=5m}",
        start_time=datetime(2026, 2, 10, 14, 30, tzinfo=timezone.utc),
        label="BULLISH OPEN",
        signal_type="OPEN",
        direction="BULLISH",
        engine="hull_macd",
        hull_direction="Up",
        hull_value=5050.0,
        macd_value=1.5,
        macd_signal=1.0,
        macd_histogram=0.5,
        close_price=5055.0,
        trigger="confluence",
    )


@patch("tastytrade.providers.subscriptions.sync_redis.Redis")
def test_publish_uses_correct_channel_format(mock_redis_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_redis_cls.return_value = mock_conn

    publisher = RedisPublisher()
    quote = make_quote()
    publisher.publish(quote)

    mock_conn.publish.assert_called_once()
    call_kwargs = mock_conn.publish.call_args
    assert call_kwargs.kwargs["channel"] == "market:QuoteEvent:SPY"


@patch("tastytrade.providers.subscriptions.sync_redis.Redis")
def test_publish_serializes_event_as_json(mock_redis_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_redis_cls.return_value = mock_conn

    publisher = RedisPublisher()
    quote = make_quote()
    publisher.publish(quote)

    call_kwargs = mock_conn.publish.call_args
    message = call_kwargs.kwargs["message"]
    parsed = json.loads(message)
    assert parsed["eventSymbol"] == "SPY"
    assert parsed["bidPrice"] == 500.0


@patch("tastytrade.providers.subscriptions.sync_redis.Redis")
def test_close_closes_redis_connection(mock_redis_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_redis_cls.return_value = mock_conn

    publisher = RedisPublisher()
    publisher.close()

    mock_conn.close.assert_called_once()


@patch("tastytrade.providers.subscriptions.sync_redis.Redis")
def test_publish_trade_signal(mock_redis_cls: MagicMock) -> None:
    mock_conn = MagicMock()
    mock_redis_cls.return_value = mock_conn

    publisher = RedisPublisher()
    signal = make_trade_signal()
    publisher.publish(signal)

    call_kwargs = mock_conn.publish.call_args
    assert call_kwargs.kwargs["channel"] == "market:TradeSignal:SPX{=5m}"
    parsed = json.loads(call_kwargs.kwargs["message"])
    assert parsed["direction"] == "BULLISH"
    assert parsed["engine"] == "hull_macd"


@patch("tastytrade.providers.subscriptions.sync_redis.Redis")
def test_engine_publish_to_redis_via_on_signal(mock_redis_cls: MagicMock) -> None:
    """Wire engine.on_signal = publisher.publish and verify Redis publish is called."""
    mock_conn = MagicMock()
    mock_redis_cls.return_value = mock_conn

    publisher = RedisPublisher()
    engine = MagicMock()
    engine.on_signal = publisher.publish

    signal = make_trade_signal()
    engine.on_signal(signal)

    mock_conn.publish.assert_called_once()
    call_kwargs = mock_conn.publish.call_args
    assert call_kwargs.kwargs["channel"] == "market:TradeSignal:SPX{=5m}"


def test_typed_deserialization_round_trip() -> None:
    """Event published to Redis deserializes back via known type."""
    quote = make_quote()
    data = json.loads(quote.model_dump_json())
    result = QuoteEvent(**data)
    assert isinstance(result, QuoteEvent)
    assert result.eventSymbol == quote.eventSymbol
    assert result.bidPrice == 500.0


def test_typed_deserialization_trade_signal_round_trip() -> None:
    """TradeSignal published to Redis deserializes back via known type."""
    signal = make_trade_signal()
    data = json.loads(signal.model_dump_json())
    result = TradeSignal(**data)
    assert isinstance(result, TradeSignal)
    assert result.direction == "BULLISH"
    assert result.engine == "hull_macd"
