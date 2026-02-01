"""Tests for CandleSnapshotTracker processor."""

import asyncio
from datetime import datetime

import pytest

from tastytrade.messaging.models.events import CandleEvent, TradeEvent
from tastytrade.messaging.processors.snapshot import (
    SNAPSHOT_BEGIN,
    SNAPSHOT_END,
    SNAPSHOT_SNIP,
    CandleSnapshotTracker,
)


def make_candle(symbol: str, flags: int | None = None) -> CandleEvent:
    """Create a CandleEvent with the given symbol and eventFlags."""
    return CandleEvent(
        eventSymbol=symbol,
        time=datetime(2026, 1, 28, 10, 0, 0),
        eventFlags=flags,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0,
    )


def test_single_symbol_completion() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")

    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_BEGIN))
    assert "AAPL{=d}" in tracker.pending_symbols

    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_END))
    assert "AAPL{=d}" not in tracker.pending_symbols
    assert "AAPL{=d}" in tracker.completed_symbols


def test_multiple_symbols_all_must_complete() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")
    tracker.register_symbol("SPY{=5m}")

    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_END))
    assert len(tracker.pending_symbols) == 1
    assert "SPY{=5m}" in tracker.pending_symbols

    tracker.process_event(make_candle("SPY{=5m}", SNAPSHOT_END))
    assert len(tracker.pending_symbols) == 0
    assert tracker.completed_symbols == {"AAPL{=d}", "SPY{=5m}"}


def test_snapshot_snip_also_completes() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("QQQ{=m}")

    tracker.process_event(make_candle("QQQ{=m}", SNAPSHOT_SNIP))
    assert "QQQ{=m}" in tracker.completed_symbols
    assert len(tracker.pending_symbols) == 0


def test_non_snapshot_flags_do_not_complete() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")

    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_BEGIN))
    assert "AAPL{=d}" in tracker.pending_symbols
    assert "AAPL{=d}" not in tracker.completed_symbols

    tracker.process_event(make_candle("AAPL{=d}", 0x00))
    assert "AAPL{=d}" in tracker.pending_symbols


def test_none_flags_ignored() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")

    tracker.process_event(make_candle("AAPL{=d}", flags=None))
    assert "AAPL{=d}" in tracker.pending_symbols


def test_unregistered_symbol_ignored() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")

    tracker.process_event(make_candle("MSFT{=d}", SNAPSHOT_END))
    assert "MSFT{=d}" not in tracker.completed_symbols
    assert "AAPL{=d}" in tracker.pending_symbols


def test_non_candle_event_ignored() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")

    trade = TradeEvent(eventSymbol="AAPL", price=150.0)
    tracker.process_event(trade)
    assert "AAPL{=d}" in tracker.pending_symbols


@pytest.mark.asyncio
async def test_wait_completes_immediately_when_empty() -> None:
    tracker = CandleSnapshotTracker()
    incomplete = await tracker.wait_for_completion(timeout=1.0)
    assert incomplete == set()


@pytest.mark.asyncio
async def test_wait_completes_when_all_snapshots_arrive() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")
    tracker.register_symbol("SPY{=5m}")

    async def deliver_snapshots() -> None:
        await asyncio.sleep(0.05)
        tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_END))
        tracker.process_event(make_candle("SPY{=5m}", SNAPSHOT_END))

    asyncio.get_event_loop().create_task(deliver_snapshots())
    incomplete = await tracker.wait_for_completion(timeout=5.0)
    assert incomplete == set()


@pytest.mark.asyncio
async def test_timeout_returns_incomplete_symbols() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")
    tracker.register_symbol("SPY{=5m}")

    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_END))

    incomplete = await tracker.wait_for_completion(timeout=0.1)
    assert incomplete == {"SPY{=5m}"}


def test_completions_queue_receives_symbols() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")
    tracker.register_symbol("SPY{=5m}")

    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_END))
    tracker.process_event(make_candle("SPY{=5m}", SNAPSHOT_END))

    assert tracker.completions.qsize() == 2
    assert tracker.completions.get_nowait() == "AAPL{=d}"
    assert tracker.completions.get_nowait() == "SPY{=5m}"


def test_completions_queue_ignores_non_completing_events() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")

    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_BEGIN))
    tracker.process_event(make_candle("AAPL{=d}", 0x00))

    assert tracker.completions.empty()


def test_reset_clears_all_state() -> None:
    tracker = CandleSnapshotTracker()
    tracker.register_symbol("AAPL{=d}")
    tracker.process_event(make_candle("AAPL{=d}", SNAPSHOT_END))

    assert len(tracker.completed_symbols) == 1
    assert tracker.completions.qsize() == 1
    tracker.reset()

    assert tracker.pending_symbols == set()
    assert tracker.completed_symbols == set()
    assert tracker.completions.empty()
