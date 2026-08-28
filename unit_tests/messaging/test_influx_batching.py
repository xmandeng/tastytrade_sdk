"""TT-157: batched InfluxDB writes — one HTTP call per flush, not per event."""

import threading
from unittest.mock import Mock

from tastytrade.messaging.models.events import QuoteEvent
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor


def make_processor(batch_size: int = 500, flush_interval: float = 30.0):
    """Processor with mocked client/write_api and a long flush interval so
    tests control flushing explicitly."""
    p = TelegrafHTTPEventProcessor.__new__(TelegrafHTTPEventProcessor)
    p.client = Mock()
    p.write_api = Mock()
    p.bucket = "test-bucket"
    p.batch_size = batch_size
    p.flush_interval_seconds = flush_interval
    p.pending = []
    p.pending_lock = threading.Lock()
    p.forming = {}
    p.forming_lock = threading.Lock()
    p.points_written = 0
    p.points_by_type = {}
    p.wake = threading.Event()
    p.closing = False
    p.flusher = threading.Thread(target=p.flush_loop, daemon=True)
    return p


def quote(symbol: str = "SPY") -> QuoteEvent:
    return QuoteEvent(
        eventSymbol=symbol, bidPrice=1.0, askPrice=2.0, bidSize=1.0, askSize=1.0
    )


class TestBatching:
    def test_events_buffer_without_immediate_write(self) -> None:
        p = make_processor()
        for _ in range(10):
            p.process_event(quote())
        p.write_api.write.assert_not_called()
        assert len(p.pending) == 10

    def test_flush_writes_one_batch_and_clears(self) -> None:
        p = make_processor()
        for _ in range(10):
            p.process_event(quote())
        p.flush_pending()
        p.write_api.write.assert_called_once()
        batch = p.write_api.write.call_args[1]["record"]
        assert len(batch) == 10
        assert p.pending == []

    def test_batch_size_sets_wake_event(self) -> None:
        p = make_processor(batch_size=5)
        for _ in range(4):
            p.process_event(quote())
        assert not p.wake.is_set()
        p.process_event(quote())
        assert p.wake.is_set()

    def test_empty_flush_writes_nothing(self) -> None:
        p = make_processor()
        p.flush_pending()
        p.write_api.write.assert_not_called()

    def test_failed_write_drops_batch_and_continues(self) -> None:
        p = make_processor()
        p.write_api.write.side_effect = RuntimeError("influx down")
        p.process_event(quote())
        p.flush_pending()  # must not raise
        assert p.pending == []
        p.write_api.write.side_effect = None
        p.process_event(quote())
        p.flush_pending()
        assert p.write_api.write.call_count == 2

    def test_close_flushes_remainder(self) -> None:
        p = make_processor()
        p.flusher.start()
        p.process_event(quote())
        p.close()
        p.write_api.write.assert_called_once()
        p.write_api.close.assert_called_once()
        p.client.close.assert_called_once()
        assert not p.flusher.is_alive()

    def test_flush_loop_wakes_on_full_batch(self) -> None:
        p = make_processor(batch_size=3)
        p.flusher.start()
        try:
            for _ in range(3):
                p.process_event(quote())
            for _ in range(100):
                if p.write_api.write.called:
                    break
                threading.Event().wait(0.02)
            p.write_api.write.assert_called_once()
            assert len(p.write_api.write.call_args[1]["record"]) == 3
        finally:
            p.close()
