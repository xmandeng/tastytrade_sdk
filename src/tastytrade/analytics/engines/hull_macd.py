"""Hull MA + MACD confluence signal detection engine.

Monitors 5-minute candle data, detects Hull MA direction change + MACD
crossover confluences, and emits TradeSignal events. Designed for SPX
0DTE trading where strict confluence is required for entry (OPEN) but
only a single indicator flip is needed for exit (CLOSE).

Bullish and bearish positions are tracked independently — a bull put
spread and bear call spread can be open simultaneously.
"""

import logging
from dataclasses import dataclass, field
from datetime import time
from typing import Callable
from zoneinfo import ZoneInfo

import polars as pl

from tastytrade.analytics.engines.models import (
    SignalDirection,
    SignalType,
    TradeSignal,
)
from tastytrade.analytics.indicators.momentum import hull, macd
from tastytrade.messaging.models.events import CandleEvent

logger = logging.getLogger(__name__)

CANDLE_CAP = 500
ET = ZoneInfo("America/New_York")
DEFAULT_EARLIEST_ENTRY = time(10, 0)
DEFAULT_LATEST_ENTRY = time(15, 0)


@dataclass
class TimeframeState:
    """Per-symbol state tracking for the position-aware state machine."""

    hull_direction: str | None = None
    macd_position: str | None = None
    hull_armed_direction: str | None = None
    macd_armed_direction: str | None = None
    bullish_open: bool = False
    bearish_open: bool = False
    candles: pl.DataFrame = field(default_factory=pl.DataFrame)


class HullMacdEngine:
    """Hull MA + MACD confluence signal detection engine.

    Accumulates candle data per symbol, computes Hull MA and MACD
    indicators on each new candle, and uses a position-aware state
    machine to detect confluence entry signals and single-indicator
    exit signals.

    Bullish and bearish positions are independent — both can be open
    at the same time (bull put spread + bear call spread).
    """

    def __init__(
        self,
        earliest_entry: time = DEFAULT_EARLIEST_ENTRY,
        latest_entry: time = DEFAULT_LATEST_ENTRY,
    ) -> None:
        self._signals: list[TradeSignal] = []
        self._on_signal: Callable[[TradeSignal], None] | None = None
        self._states: dict[str, TimeframeState] = {}
        self._prior_closes: dict[str, float] = {}
        self._earliest_entry = earliest_entry
        self._latest_entry = latest_entry

    @property
    def name(self) -> str:
        return "hull_macd"

    @property
    def signals(self) -> list[TradeSignal]:
        return self._signals

    @property
    def on_signal(self) -> Callable[[TradeSignal], None] | None:
        return self._on_signal

    @on_signal.setter
    def on_signal(self, callback: Callable[[TradeSignal], None] | None) -> None:
        self._on_signal = callback

    def set_prior_close(self, event_symbol: str, price: float) -> None:
        self._prior_closes[event_symbol] = price

    def on_candle_event(self, event: CandleEvent) -> None:
        if event.close is None:
            return

        symbol = event.eventSymbol
        state = self._get_or_create_state(symbol)

        self._accumulate(state, event)

        if state.candles.height < 2:
            return

        hull_dir = self._compute_hull(state, symbol)
        macd_pos = self._compute_macd(state, symbol)

        if hull_dir is None or macd_pos is None:
            return

        prev_hull = state.hull_direction
        prev_macd = state.macd_position
        state.hull_direction = hull_dir
        state.macd_position = macd_pos

        hull_changed = prev_hull is not None and hull_dir != prev_hull
        macd_changed = prev_macd is not None and macd_pos != prev_macd

        # Before earliest_entry: indicators warm up but no signals
        candle_et = event.time.astimezone(ET).time()
        if candle_et < self._earliest_entry:
            return

        # CLOSEs always fire — must be able to exit positions
        self._handle_closes(
            state, event, hull_changed, hull_dir, macd_changed, macd_pos
        )

        # No new OPENs during power hour
        if candle_et >= self._latest_entry:
            return

        self._handle_opens(state, event, hull_changed, hull_dir, macd_changed, macd_pos)

    def _get_or_create_state(self, symbol: str) -> TimeframeState:
        if symbol not in self._states:
            self._states[symbol] = TimeframeState()
        return self._states[symbol]

    def _accumulate(self, state: TimeframeState, event: CandleEvent) -> None:
        row = pl.DataFrame([event])
        if state.candles.height == 0:
            state.candles = row
        else:
            state.candles = (
                state.candles.vstack(row)
                .unique(subset=["eventSymbol", "time"], keep="last")
                .sort("time", descending=False)
            )
        if state.candles.height > CANDLE_CAP:
            state.candles = state.candles.tail(CANDLE_CAP)

    def _compute_hull(self, state: TimeframeState, symbol: str) -> str | None:
        pad_value = self._prior_closes.get(symbol)
        hull_df = hull(state.candles, pad_value=pad_value)
        if hull_df.empty:
            return None
        return str(hull_df["HMA_color"].iloc[-1])

    def _compute_macd(self, state: TimeframeState, symbol: str) -> str | None:
        prior_close = self._prior_closes.get(symbol)
        macd_df = macd(state.candles, prior_close=prior_close)
        if macd_df.height == 0:
            return None
        last_row = macd_df.tail(1)
        value = last_row["Value"][0]
        avg = last_row["avg"][0]
        return "bullish" if value > avg else "bearish"

    def _handle_closes(
        self,
        state: TimeframeState,
        event: CandleEvent,
        hull_changed: bool,
        hull_dir: str,
        macd_changed: bool,
        macd_pos: str,
    ) -> None:
        if state.bullish_open:
            if hull_changed and hull_dir == "Down":
                self._emit_signal(
                    state,
                    event,
                    SignalType.CLOSE,
                    SignalDirection.BULLISH.value,
                    "hull",
                )
                state.bullish_open = False
            elif macd_changed and macd_pos == "bearish":
                self._emit_signal(
                    state,
                    event,
                    SignalType.CLOSE,
                    SignalDirection.BULLISH.value,
                    "macd",
                )
                state.bullish_open = False

        if state.bearish_open:
            if hull_changed and hull_dir == "Up":
                self._emit_signal(
                    state,
                    event,
                    SignalType.CLOSE,
                    SignalDirection.BEARISH.value,
                    "hull",
                )
                state.bearish_open = False
            elif macd_changed and macd_pos == "bullish":
                self._emit_signal(
                    state,
                    event,
                    SignalType.CLOSE,
                    SignalDirection.BEARISH.value,
                    "macd",
                )
                state.bearish_open = False

    def _handle_opens(
        self,
        state: TimeframeState,
        event: CandleEvent,
        hull_changed: bool,
        hull_dir: str,
        macd_changed: bool,
        macd_pos: str,
    ) -> None:
        hull_signal_dir = self._hull_to_signal_direction(hull_dir)
        macd_signal_dir = self._macd_to_signal_direction(macd_pos)

        if hull_changed:
            state.hull_armed_direction = hull_signal_dir
        if macd_changed:
            state.macd_armed_direction = macd_signal_dir

        if state.hull_armed_direction and state.macd_armed_direction:
            if state.hull_armed_direction == state.macd_armed_direction:
                direction = state.hull_armed_direction
                already_open = (
                    direction == SignalDirection.BULLISH.value and state.bullish_open
                ) or (direction == SignalDirection.BEARISH.value and state.bearish_open)
                if not already_open:
                    self._emit_signal(
                        state, event, SignalType.OPEN, direction, "confluence"
                    )
                    if direction == SignalDirection.BULLISH.value:
                        state.bullish_open = True
                    else:
                        state.bearish_open = True
                    state.hull_armed_direction = None
                    state.macd_armed_direction = None
            else:
                # Opposing armed directions — discard the older one
                if hull_changed and not macd_changed:
                    state.macd_armed_direction = None
                elif macd_changed and not hull_changed:
                    state.hull_armed_direction = None
                else:
                    state.hull_armed_direction = None
                    state.macd_armed_direction = None

    def _emit_signal(
        self,
        state: TimeframeState,
        event: CandleEvent,
        signal_type: SignalType,
        direction: str,
        trigger: str,
    ) -> None:
        macd_df = macd(
            state.candles, prior_close=self._prior_closes.get(event.eventSymbol)
        )
        last_row = macd_df.tail(1)
        macd_value = float(last_row["Value"][0])
        macd_signal_val = float(last_row["avg"][0])
        macd_histogram = float(last_row["diff"][0])

        pad_value = self._prior_closes.get(event.eventSymbol)
        hull_df = hull(state.candles, pad_value=pad_value)
        hull_value = float(hull_df["HMA"].iloc[-1])

        color = "#55A868" if direction == SignalDirection.BULLISH.value else "#8C8C8C"
        label = f"{signal_type.value} {direction}"

        signal = TradeSignal(
            eventSymbol=event.eventSymbol,
            start_time=event.time,
            label=label,
            color=color,
            line_width=0.5,
            line_dash="dot",
            opacity=0.4,
            signal_type=signal_type.value,
            direction=direction,
            engine=self.name,
            hull_direction=state.hull_direction or "Unknown",
            hull_value=hull_value,
            macd_value=macd_value,
            macd_signal=macd_signal_val,
            macd_histogram=macd_histogram,
            close_price=float(event.close),  # type: ignore[arg-type]
            trigger=trigger,
        )

        self._signals.append(signal)

        logger.info(
            "TradeSignal: %s %s %s at %s (trigger=%s)",
            signal.signal_type,
            signal.direction,
            signal.eventSymbol,
            signal.start_time.isoformat(),
            signal.trigger,
            extra={
                "signal_type": signal.signal_type,
                "signal_direction": signal.direction,
                "signal_engine": signal.engine,
                "signal_trigger": signal.trigger,
                "hull_direction": signal.hull_direction,
                "hull_value": signal.hull_value,
                "macd_value": signal.macd_value,
                "macd_signal": signal.macd_signal,
                "macd_histogram": signal.macd_histogram,
                "close_price": signal.close_price,
                "event_symbol": signal.eventSymbol,
            },
        )

        if self._on_signal:
            self._on_signal(signal)

    @staticmethod
    def _hull_to_signal_direction(hull_dir: str) -> str:
        return (
            SignalDirection.BULLISH.value
            if hull_dir == "Up"
            else SignalDirection.BEARISH.value
        )

    @staticmethod
    def _macd_to_signal_direction(macd_pos: str) -> str:
        return (
            SignalDirection.BULLISH.value
            if macd_pos == "bullish"
            else SignalDirection.BEARISH.value
        )
