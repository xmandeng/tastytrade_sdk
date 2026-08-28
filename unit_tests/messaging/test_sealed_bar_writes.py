"""TT-159: sealed-bar candle writes — one Influx write per bar, on roll."""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from tastytrade.messaging.models.events import CandleEvent, QuoteEvent
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor

T0 = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)


def make_processor():
    p = TelegrafHTTPEventProcessor.__new__(TelegrafHTTPEventProcessor)
    p.client = Mock()
    p.write_api = Mock()
    p.bucket = "test"
    p.batch_size = 500
    p.flush_interval_seconds = 30.0
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


def bar(t: datetime, close: float, symbol: str = "SPX{=m}") -> CandleEvent:
    return CandleEvent(
        eventSymbol=symbol, time=t, open=close, high=close, low=close, close=close
    )


class TestSealedBarWrites:
    def test_forming_updates_are_held_not_written(self) -> None:
        p = make_processor()
        for close in (1.0, 2.0, 3.0):
            p.process_event(bar(T0, close))
        assert p.pending == []
        assert p.forming["SPX{=m}"][1].close == 3.0

    def test_roll_writes_previous_bar_final_state_once(self) -> None:
        p = make_processor()
        p.process_event(bar(T0, 1.0))
        p.process_event(bar(T0, 2.5))  # final state of bar T0
        p.process_event(bar(T0 + timedelta(minutes=1), 9.0))  # roll
        assert len(p.pending) == 1
        assert p.points_written == 1
        assert p.forming["SPX{=m}"][1].close == 9.0

    def test_symbols_roll_independently(self) -> None:
        p = make_processor()
        p.process_event(bar(T0, 1.0, "SPX{=m}"))
        p.process_event(bar(T0, 5.0, "SPX{=5m}"))
        p.process_event(bar(T0 + timedelta(minutes=1), 2.0, "SPX{=m}"))
        assert len(p.pending) == 1  # only the 1m bar rolled

    def test_out_of_order_bar_writes_through(self) -> None:
        p = make_processor()
        p.process_event(bar(T0, 1.0))
        p.process_event(bar(T0 - timedelta(minutes=5), 0.5))  # backfill replay
        assert len(p.pending) == 1
        assert p.forming["SPX{=m}"][1].close == 1.0  # newer bar still held

    def test_non_candle_events_pass_through(self) -> None:
        p = make_processor()
        p.process_event(
            QuoteEvent(
                eventSymbol="SPY", bidPrice=1.0, askPrice=2.0, bidSize=1.0, askSize=1.0
            )
        )
        assert len(p.pending) == 1

    def test_close_flushes_held_bars(self) -> None:
        p = make_processor()
        p.flusher.start()
        p.process_event(bar(T0, 1.0, "SPX{=m}"))
        p.process_event(bar(T0, 5.0, "SPX{=5m}"))
        p.close()
        p.write_api.write.assert_called_once()
        batch = p.write_api.write.call_args[1]["record"]
        assert len(batch) == 2  # both held bars flushed on graceful close
        assert p.forming == {}
