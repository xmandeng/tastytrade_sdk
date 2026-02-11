"""Tests for the SignalEventProcessor adapter."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from tastytrade.messaging.models.events import CandleEvent, QuoteEvent
from tastytrade.messaging.processors.signal import SignalEventProcessor


def make_candle() -> CandleEvent:
    return CandleEvent(
        eventSymbol="SPX{=5m}",
        time=datetime(2026, 2, 10, 14, 30, tzinfo=timezone.utc),
        open=5000.0,
        high=5000.0,
        low=5000.0,
        close=5000.0,
    )


def test_processor_name_is_signal():
    engine = MagicMock()
    proc = SignalEventProcessor(engine=engine)
    assert proc.name == "signal"


def test_processor_routes_candle_to_engine():
    engine = MagicMock()
    proc = SignalEventProcessor(engine=engine)
    candle = make_candle()
    proc.process_event(candle)
    engine.on_candle_event.assert_called_once_with(candle)


def test_processor_ignores_non_candle_events():
    engine = MagicMock()
    proc = SignalEventProcessor(engine=engine)
    quote = QuoteEvent(
        eventSymbol="SPX",
        bidPrice=5000.0,
        askPrice=5001.0,
        bidSize=100.0,
        askSize=100.0,
    )
    proc.process_event(quote)
    engine.on_candle_event.assert_not_called()


def test_processor_close_logs_signal_count(caplog):
    engine = MagicMock()
    proc = SignalEventProcessor(engine=engine)
    proc._signal_count = 5
    with caplog.at_level("INFO"):
        proc.close()
    assert "5 signals emitted" in caplog.text
