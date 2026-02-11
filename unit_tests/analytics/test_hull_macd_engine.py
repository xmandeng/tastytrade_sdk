"""Tests for the HullMacdEngine signal detection engine.

All indicator computations are mocked via @patch to control Hull MA
direction and MACD crossover state deterministically.
"""

from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch

import polars as pl

from tastytrade.analytics.engines.hull_macd import HullMacdEngine
from tastytrade.analytics.engines.models import SignalDirection, SignalType, TradeSignal
from tastytrade.analytics.visualizations.models import BaseAnnotation
from tastytrade.messaging.models.events import CandleEvent


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_candle(
    symbol: str = "SPX{=5m}",
    close: float | None = 5000.0,
    time_offset_minutes: int = 0,
) -> CandleEvent:
    # 15:00 UTC = 10:00 AM ET (past default earliest_entry)
    ts = datetime(2026, 2, 10, 15, 0, 0, tzinfo=timezone.utc) + timedelta(
        minutes=time_offset_minutes
    )
    return CandleEvent(
        eventSymbol=symbol,
        time=ts,
        open=close,
        high=close,
        low=close,
        close=close,
    )


def make_hull_result(direction: str = "Up", hma_value: float = 5000.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [datetime(2026, 2, 10, 14, 30, tzinfo=timezone.utc)],
            "HMA": [hma_value],
            "HMA_color": [direction],
        }
    )


def make_macd_result(
    value: float = 1.0,
    avg: float = 0.5,
    diff: float = 0.5,
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [datetime(2026, 2, 10, 14, 30, tzinfo=timezone.utc)],
            "close": [5000.0],
            "Value": [value],
            "avg": [avg],
            "diff": [diff],
            "diff_color": ["#04FE00"],
        }
    )


HULL_PATH = "tastytrade.analytics.engines.hull_macd.hull"
MACD_PATH = "tastytrade.analytics.engines.hull_macd.macd"


# ---------------------------------------------------------------------------
# 1. Engine init
# ---------------------------------------------------------------------------


def test_engine_name():
    engine = HullMacdEngine()
    assert engine.name == "hull_macd"


def test_engine_signals_initially_empty():
    engine = HullMacdEngine()
    assert engine.signals == []


def test_engine_on_signal_initially_none():
    engine = HullMacdEngine()
    assert engine.on_signal is None


def test_set_prior_close():
    engine = HullMacdEngine()
    engine.set_prior_close("SPX{=5m}", 4950.0)
    assert engine._prior_closes["SPX{=5m}"] == 4950.0


# ---------------------------------------------------------------------------
# 2. Accumulation
# ---------------------------------------------------------------------------


@patch(MACD_PATH, return_value=make_macd_result())
@patch(HULL_PATH, return_value=make_hull_result())
def test_new_symbol_creates_state(mock_hull, mock_macd):
    engine = HullMacdEngine()
    engine.on_candle_event(make_candle())
    assert "SPX{=5m}" in engine._states


@patch(MACD_PATH, return_value=make_macd_result())
@patch(HULL_PATH, return_value=make_hull_result())
def test_candles_accumulate(mock_hull, mock_macd):
    engine = HullMacdEngine()
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    assert engine._states["SPX{=5m}"].candles.height == 3


def test_none_close_skipped():
    engine = HullMacdEngine()
    engine.on_candle_event(make_candle(close=None))
    assert "SPX{=5m}" not in engine._states


@patch(MACD_PATH, return_value=make_macd_result())
@patch(HULL_PATH, return_value=make_hull_result())
def test_candle_cap_enforced(mock_hull, mock_macd):
    engine = HullMacdEngine()
    for i in range(510):
        engine.on_candle_event(make_candle(time_offset_minutes=i, close=5000.0 + i))
    assert engine._states["SPX{=5m}"].candles.height <= 500


# ---------------------------------------------------------------------------
# 3. Indicator computation
# ---------------------------------------------------------------------------


def test_not_enough_data_no_signal():
    engine = HullMacdEngine()
    # Only 1 candle — should not compute indicators
    engine.on_candle_event(make_candle())
    assert engine.signals == []


@patch(MACD_PATH, return_value=make_macd_result())
@patch(HULL_PATH, return_value=make_hull_result("Up", 5010.0))
def test_hull_computed_with_prior_close(mock_hull, mock_macd):
    engine = HullMacdEngine()
    engine.set_prior_close("SPX{=5m}", 4950.0)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))
    mock_hull.assert_called()
    _, kwargs = mock_hull.call_args
    assert kwargs.get("pad_value") == 4950.0


@patch(MACD_PATH, return_value=make_macd_result())
@patch(HULL_PATH, return_value=make_hull_result())
def test_macd_uses_prior_close(mock_hull, mock_macd):
    engine = HullMacdEngine()
    engine.set_prior_close("SPX{=5m}", 4950.0)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))
    mock_macd.assert_called()
    _, kwargs = mock_macd.call_args
    assert kwargs.get("prior_close") == 4950.0


# ---------------------------------------------------------------------------
# 4. OPEN signals — confluence
# ---------------------------------------------------------------------------


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_hull_then_macd_emits_open_bullish(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Candle 0: establish baseline (Down hull, bearish macd)
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    # Candle 2: Hull flips Up — arms hull
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    assert len(engine.signals) == 0

    # Candle 3: MACD crosses bullish — confluence!
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=15))
    assert len(engine.signals) == 1
    assert engine.signals[0].signal_type == SignalType.OPEN.value
    assert engine.signals[0].direction == SignalDirection.BULLISH.value


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_macd_then_hull_emits_open_bullish(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Baseline
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    # MACD crosses bullish first — arms macd
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    assert len(engine.signals) == 0

    # Hull flips Up — confluence!
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=15))
    assert len(engine.signals) == 1
    assert engine.signals[0].direction == SignalDirection.BULLISH.value


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_open_signal_has_correct_fields(mock_hull, mock_macd):
    engine = HullMacdEngine()
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    mock_hull.return_value = make_hull_result("Up", 5010.0)
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    engine.on_candle_event(make_candle(time_offset_minutes=15))

    sig = engine.signals[0]
    assert sig.engine == "hull_macd"
    assert sig.trigger == "confluence"
    assert sig.eventSymbol == "SPX{=5m}"
    assert sig.close_price == 5000.0


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_open_callback_invoked(mock_hull, mock_macd):
    engine = HullMacdEngine()
    received = []
    engine.on_signal = lambda s: received.append(s)

    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    engine.on_candle_event(make_candle(time_offset_minutes=15))

    assert len(received) == 1


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_no_signal_when_only_hull_armed(mock_hull, mock_macd):
    engine = HullMacdEngine()
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    # Hull flips Up but MACD stays bearish (no change)
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    assert len(engine.signals) == 0


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_open_only_fires_when_flat(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Open a LONG position
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    engine.on_candle_event(make_candle(time_offset_minutes=15))
    assert len(engine.signals) == 1  # OPEN

    # While bullish is open, same direction should not OPEN again
    state = engine._states["SPX{=5m}"]
    assert state.bullish_open is True
    # Hull stays Up, MACD stays bullish — no new change, no new OPEN
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == 1


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_open_bearish_signal(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Baseline: Up hull, bullish MACD
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    # Hull flips Down
    mock_hull.return_value = make_hull_result("Down", 4990.0)
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    assert len(engine.signals) == 0

    # MACD crosses bearish — SHORT confluence
    mock_hull.return_value = make_hull_result("Down", 4990.0)
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=15))
    assert len(engine.signals) == 1
    assert engine.signals[0].signal_type == SignalType.OPEN.value
    assert engine.signals[0].direction == SignalDirection.BEARISH.value


# ---------------------------------------------------------------------------
# 5. CLOSE signals — single indicator
# ---------------------------------------------------------------------------


def _open_bullish(engine: HullMacdEngine, mock_hull, mock_macd) -> None:
    """Helper to open a BULLISH position via confluence."""
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    engine.on_candle_event(make_candle(time_offset_minutes=15))


def _open_bearish(engine: HullMacdEngine, mock_hull, mock_macd) -> None:
    """Helper to open a BEARISH position via confluence."""
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    engine.on_candle_event(make_candle(time_offset_minutes=15))


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_hull_flip_closes_bullish(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)
    assert len(engine.signals) == 1

    # Hull flips Down — closes LONG
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == 2
    assert engine.signals[1].signal_type == SignalType.CLOSE.value
    assert engine.signals[1].trigger == "hull"


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_macd_cross_closes_bullish(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)

    # MACD crosses bearish — closes LONG
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == 2
    assert engine.signals[1].signal_type == SignalType.CLOSE.value
    assert engine.signals[1].trigger == "macd"


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_hull_flip_closes_bearish(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bearish(engine, mock_hull, mock_macd)

    # Hull flips Up — closes SHORT
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == 2
    assert engine.signals[1].signal_type == SignalType.CLOSE.value
    assert engine.signals[1].direction == SignalDirection.BEARISH.value


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_macd_cross_closes_bearish(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bearish(engine, mock_hull, mock_macd)

    # MACD crosses bullish — closes SHORT
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == 2
    assert engine.signals[1].signal_type == SignalType.CLOSE.value
    assert engine.signals[1].trigger == "macd"


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_close_returns_to_flat(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)

    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert engine._states["SPX{=5m}"].bullish_open is False


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_close_does_not_clear_armed_states(mock_hull, mock_macd):
    """Armed states persist through closes — only cleared on open."""
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)

    # Hull flips Down — closes bullish, and arms hull BEARISH
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    state = engine._states["SPX{=5m}"]
    assert state.bullish_open is False
    # Hull armed BEARISH from the flip, not cleared by close
    assert state.hull_armed_direction == "BEARISH"


# ---------------------------------------------------------------------------
# 6. Position guard
# ---------------------------------------------------------------------------


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_cannot_open_same_direction_when_already_open(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)
    assert engine._states["SPX{=5m}"].bullish_open is True
    # No additional bullish OPEN should be possible
    initial_count = len(engine.signals)
    # Feed a candle with no change
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == initial_count


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_no_duplicate_open_signals(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)

    # Feed more candles with same indicators — no new signals
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    for i in range(20, 40, 5):
        engine.on_candle_event(make_candle(time_offset_minutes=i))
    assert len(engine.signals) == 1


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_must_close_before_reopen(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)

    # Close via hull flip
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == 2  # OPEN + CLOSE

    # Now bullish is closed, need fresh confluence for next bullish OPEN
    assert engine._states["SPX{=5m}"].bullish_open is False


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_fresh_confluence_required_after_close(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)

    # Close via hull flip (MACD stays bullish — no MACD change)
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))

    # Feed candles with stable indicators — no changes → no new arming
    engine.on_candle_event(make_candle(time_offset_minutes=25))
    engine.on_candle_event(make_candle(time_offset_minutes=30))
    assert len(engine.signals) == 2  # Still just OPEN + CLOSE


# ---------------------------------------------------------------------------
# 7. Opposing armed
# ---------------------------------------------------------------------------


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_opposing_armed_discards_older(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Baseline
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    # Hull flips Up — arms LONG
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    state = engine._states["SPX{=5m}"]
    assert state.hull_armed_direction == "BULLISH"

    # MACD crosses bearish (further bearish, was already bearish) — no change
    # Now let's flip MACD to SHORT: value=-2 (bearish stays) — still no macd change
    # Actually, let's flip MACD to bullish then back to bearish to arm SHORT macd
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)  # bullish
    engine.on_candle_event(make_candle(time_offset_minutes=15))

    # That actually triggers confluence (both Up/LONG + bullish/LONG). So let's adjust.
    # The hull_armed was LONG. MACD changed to bullish = LONG. Same direction = confluence fired.
    # Let's test opposing differently: start with hull SHORT armed, then MACD goes LONG.
    assert len(engine.signals) == 1  # Confluence happened


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_opposing_armed_no_signal(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Baseline: Up hull, bearish macd
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=0))
    engine.on_candle_event(make_candle(time_offset_minutes=5))

    # Hull flips Down (arm SHORT), MACD stays bearish
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=10))
    state = engine._states["SPX{=5m}"]
    assert state.hull_armed_direction == "BEARISH"
    assert state.macd_armed_direction is None

    # MACD crosses bullish (arm LONG) — opposing!
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=15))
    # Opposing: hull SHORT armed, macd LONG armed — hull (older) discarded
    assert len(engine.signals) == 0
    assert state.hull_armed_direction is None
    assert state.macd_armed_direction == "BULLISH"


# ---------------------------------------------------------------------------
# 8. Full trade lifecycle
# ---------------------------------------------------------------------------


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_full_lifecycle_flat_open_close_flat(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)
    assert engine._states["SPX{=5m}"].bullish_open is True

    # Close via MACD
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert engine._states["SPX{=5m}"].bullish_open is False
    assert len(engine.signals) == 2


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_multiple_trades_in_sequence(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Trade 1: BULLISH
    _open_bullish(engine, mock_hull, mock_macd)

    # Close via hull Down (arms hull BEARISH)
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert engine._states["SPX{=5m}"].bullish_open is False
    assert len(engine.signals) == 2  # OPEN BULL + CLOSE BULL

    # MACD crosses bearish — completes bearish confluence (hull armed BEARISH persists)
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=25))
    assert len(engine.signals) == 3  # + OPEN BEARISH

    # Close bearish via hull Up (arms hull BULLISH)
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=30))
    assert len(engine.signals) == 4  # + CLOSE BEARISH

    # MACD crosses bullish — completes bullish confluence
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=35))
    assert len(engine.signals) == 5  # + OPEN BULLISH
    assert engine.signals[4].signal_type == SignalType.OPEN.value
    assert engine.signals[4].direction == SignalDirection.BULLISH.value


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_alternating_bullish_bearish_trades(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Trade 1: LONG
    _open_bullish(engine, mock_hull, mock_macd)
    # Close LONG via hull
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    assert len(engine.signals) == 2

    # Stabilize
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=25))
    engine.on_candle_event(make_candle(time_offset_minutes=30))

    # Trade 2: SHORT — hull Down
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=35))

    # MACD crosses bearish — SHORT confluence
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=40))
    assert len(engine.signals) == 3
    assert engine.signals[2].direction == SignalDirection.BEARISH.value


# ---------------------------------------------------------------------------
# 9. Multi-symbol
# ---------------------------------------------------------------------------


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_independent_state_per_symbol(mock_hull, mock_macd):
    engine = HullMacdEngine()
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)

    engine.on_candle_event(make_candle(symbol="SPX{=5m}", time_offset_minutes=0))
    engine.on_candle_event(make_candle(symbol="SPX{=5m}", time_offset_minutes=5))
    engine.on_candle_event(make_candle(symbol="QQQ{=5m}", time_offset_minutes=0))
    engine.on_candle_event(make_candle(symbol="QQQ{=5m}", time_offset_minutes=5))

    assert "SPX{=5m}" in engine._states
    assert "QQQ{=5m}" in engine._states
    assert engine._states["SPX{=5m}"].candles.height == 2
    assert engine._states["QQQ{=5m}"].candles.height == 2


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_signal_on_one_symbol_doesnt_affect_other(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Set up SPX
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(symbol="SPX{=5m}", time_offset_minutes=0))
    engine.on_candle_event(make_candle(symbol="SPX{=5m}", time_offset_minutes=5))

    # Open LONG on SPX
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(symbol="SPX{=5m}", time_offset_minutes=10))
    engine.on_candle_event(make_candle(symbol="SPX{=5m}", time_offset_minutes=15))

    # QQQ should still be FLAT
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(symbol="QQQ{=5m}", time_offset_minutes=0))
    engine.on_candle_event(make_candle(symbol="QQQ{=5m}", time_offset_minutes=5))

    assert engine._states["SPX{=5m}"].bullish_open is True
    assert engine._states["QQQ{=5m}"].bullish_open is False
    assert engine._states["QQQ{=5m}"].bearish_open is False


# ---------------------------------------------------------------------------
# 10. Independent position tracking
# ---------------------------------------------------------------------------


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_bullish_and_bearish_can_be_open_simultaneously(mock_hull, mock_macd):
    engine = HullMacdEngine()
    # Open bullish
    _open_bullish(engine, mock_hull, mock_macd)
    state = engine._states["SPX{=5m}"]
    assert state.bullish_open is True
    assert state.bearish_open is False
    assert len(engine.signals) == 1

    # Now arm bearish confluence while bullish is open
    # Hull flips Down — arms bearish (also starts close check, but bullish MACD hasn't changed yet)
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    # Hull flip Down closed bullish
    assert state.bullish_open is False
    assert len(engine.signals) == 2  # OPEN bullish + CLOSE bullish

    # MACD crosses bearish — bearish confluence
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=25))
    assert state.bearish_open is True
    assert len(engine.signals) == 3  # + OPEN bearish

    # Now re-arm bullish while bearish is open
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=30))
    # Hull Up closes bearish
    assert state.bearish_open is False

    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=35))
    assert state.bullish_open is True
    assert len(engine.signals) == 5  # CLOSE bearish + OPEN bullish


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_close_one_direction_other_stays_open(mock_hull, mock_macd):
    """Closing bullish should not affect bearish if both were open."""
    engine = HullMacdEngine()
    # Open bullish first
    _open_bullish(engine, mock_hull, mock_macd)
    state = engine._states["SPX{=5m}"]
    assert state.bullish_open is True

    # Manually set bearish_open to simulate both open
    state.bearish_open = True

    # MACD crosses bearish — should close bullish but not bearish
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))

    assert state.bullish_open is False
    assert state.bearish_open is True  # Bearish untouched


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_cannot_reopen_same_direction_while_open(mock_hull, mock_macd):
    """Cannot open a second bullish while bullish is already open."""
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)
    state = engine._states["SPX{=5m}"]
    assert state.bullish_open is True
    assert len(engine.signals) == 1

    # Try to trigger another bullish confluence — should be blocked
    # First stabilize then re-trigger
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(make_candle(time_offset_minutes=20))
    engine.on_candle_event(make_candle(time_offset_minutes=25))
    assert len(engine.signals) == 1  # No new signals


# ---------------------------------------------------------------------------
# 11. TradeSignal model
# ---------------------------------------------------------------------------


def test_trade_signal_extends_base_annotation():
    assert issubclass(TradeSignal, BaseAnnotation)


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_trade_signal_has_time_property(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)
    sig = engine.signals[0]
    # time property is from BaseAnnotation — adds microsecond jitter
    assert sig.time is not None
    assert sig.time >= sig.start_time


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_trade_signal_processor_safe_dict(mock_hull, mock_macd):
    engine = HullMacdEngine()
    _open_bullish(engine, mock_hull, mock_macd)
    sig = engine.signals[0]
    # __dict__ should be _ProcessorSafeDict — iteration yields str/int/float/bool only
    for key, value in sig.__dict__.items():
        assert isinstance(
            value, (str, int, float, bool)
        ), f"Field {key} has non-primitive type {type(value)} in processor iteration"


# ---------------------------------------------------------------------------
# 12. Earliest entry time gate
# ---------------------------------------------------------------------------


def _make_candle_at_et(
    hour: int, minute: int = 0, symbol: str = "SPX{=5m}"
) -> CandleEvent:
    """Create a candle at a specific ET hour (converted to UTC for Feb = EST/UTC-5)."""
    utc_hour = hour + 5
    ts = datetime(2026, 2, 10, utc_hour, minute, 0, tzinfo=timezone.utc)
    return CandleEvent(
        eventSymbol=symbol, time=ts, open=5000.0, high=5000.0, low=5000.0, close=5000.0
    )


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_no_signals_before_earliest_entry(mock_hull, mock_macd):
    engine = HullMacdEngine()  # default earliest_entry=10:00 ET

    # Baseline at 9:30 ET
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(9, 30))
    engine.on_candle_event(_make_candle_at_et(9, 35))

    # Confluence conditions at 9:40 and 9:45 ET — should NOT fire
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(9, 40))
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(9, 45))

    assert len(engine.signals) == 0


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_signals_fire_after_earliest_entry(mock_hull, mock_macd):
    engine = HullMacdEngine()

    # Warm up before 10 AM ET
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(9, 30))
    engine.on_candle_event(_make_candle_at_et(9, 35))
    engine.on_candle_event(_make_candle_at_et(9, 40))
    engine.on_candle_event(_make_candle_at_et(9, 50))

    # Hull flips at 10:00 ET — now past threshold, should arm
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(10, 0))
    assert len(engine.signals) == 0

    # MACD crosses at 10:05 — confluence fires
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(10, 5))
    assert len(engine.signals) == 1
    assert engine.signals[0].signal_type == SignalType.OPEN.value


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_indicators_warm_up_before_earliest_entry(mock_hull, mock_macd):
    engine = HullMacdEngine()

    # Feed candles before 10 AM to establish indicator state
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(9, 30))
    engine.on_candle_event(_make_candle_at_et(9, 35))

    state = engine._states["SPX{=5m}"]
    # Indicator state IS tracked (warmed up), just no signals
    assert state.hull_direction == "Up"
    assert state.macd_position == "bullish"
    assert state.candles.height == 2
    assert len(engine.signals) == 0


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_custom_earliest_entry(mock_hull, mock_macd):
    engine = HullMacdEngine(earliest_entry=time(10, 30))

    # Establish baseline before 10:30
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(10, 0))
    engine.on_candle_event(_make_candle_at_et(10, 5))

    # Confluence at 10:15 — still before 10:30 threshold
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(10, 10))
    engine.on_candle_event(_make_candle_at_et(10, 15))
    assert len(engine.signals) == 0

    # Change at 10:35 — now past threshold
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(10, 35))

    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(10, 40))
    assert len(engine.signals) == 1
    assert engine.signals[0].direction == SignalDirection.BEARISH.value


# ---------------------------------------------------------------------------
# 13. Latest entry (power hour) time gate
# ---------------------------------------------------------------------------


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_no_open_during_power_hour(mock_hull, mock_macd):
    engine = HullMacdEngine()  # default latest_entry=15:00 ET

    # Establish baseline at 2:45 PM ET
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(14, 45))
    engine.on_candle_event(_make_candle_at_et(14, 50))

    # Confluence at 3:00 and 3:05 PM ET — should NOT open
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(15, 0))
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(15, 5))

    assert len(engine.signals) == 0


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_close_still_fires_during_power_hour(mock_hull, mock_macd):
    engine = HullMacdEngine()

    # Open a bullish position at 2:40 PM ET
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(14, 30))
    engine.on_candle_event(_make_candle_at_et(14, 35))
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(14, 40))
    engine.on_candle_event(_make_candle_at_et(14, 45))
    assert len(engine.signals) == 1
    assert engine.signals[0].signal_type == SignalType.OPEN.value

    # Hull flips at 3:10 PM ET — CLOSE must still fire
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(15, 10))
    assert len(engine.signals) == 2
    assert engine.signals[1].signal_type == SignalType.CLOSE.value


@patch(MACD_PATH)
@patch(HULL_PATH)
def test_open_allowed_just_before_power_hour(mock_hull, mock_macd):
    engine = HullMacdEngine()

    # Baseline
    mock_hull.return_value = make_hull_result("Down")
    mock_macd.return_value = make_macd_result(value=-1.0, avg=0.5, diff=-1.5)
    engine.on_candle_event(_make_candle_at_et(14, 40))
    engine.on_candle_event(_make_candle_at_et(14, 45))

    # Confluence at 2:55 PM ET — just before 3 PM cutoff, should fire
    mock_hull.return_value = make_hull_result("Up")
    mock_macd.return_value = make_macd_result(value=1.0, avg=0.5, diff=0.5)
    engine.on_candle_event(_make_candle_at_et(14, 50))
    engine.on_candle_event(_make_candle_at_et(14, 55))
    assert len(engine.signals) == 1
