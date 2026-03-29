"""Streaming-aware indicator wrappers for Hull MA and MACD.

Wraps the batch functions in analytics/indicators/momentum.py with
incremental state so each new candle produces one new indicator point
without recomputing the entire series.

The batch functions are used to seed initial state from historical data.
After that, each candle update calls the streaming methods.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import polars as pl

from tastytrade.analytics.indicators.momentum import (
    ema_with_seed,
    hull,
    macd,
    padded_wma,
)


@dataclass
class HullState:
    """Rolling state for incremental Hull Moving Average computation."""

    length: int = 20
    half_length: int = 0
    sqrt_length: int = 0
    pad_value: float = 0.0

    # Rolling windows for the three WMAs
    wma_half_window: list[float] = field(default_factory=list)
    wma_full_window: list[float] = field(default_factory=list)
    wma_sqrt_window: list[float] = field(default_factory=list)

    prev_hma: float | None = None

    def __post_init__(self) -> None:
        self.half_length = round(self.length / 2)
        self.sqrt_length = round(math.sqrt(self.length))


@dataclass
class MacdState:
    """Rolling state for incremental MACD computation."""

    fast_length: int = 12
    slow_length: int = 26
    macd_length: int = 9

    fast_ema: float = 0.0
    slow_ema: float = 0.0
    signal_ema: float = 0.0
    prev_histogram: float = 0.0


def compute_wma(window: list[float], period: int) -> float:
    """Compute weighted moving average for a single window."""
    weights = np.arange(1, period + 1, dtype=float)
    arr = np.array(window[-period:], dtype=float)
    if len(arr) < period:
        pad = np.full(period - len(arr), window[0] if window else 0.0)
        arr = np.concatenate((pad, arr))
    return float(np.dot(arr, weights) / weights.sum())


class StreamingIndicators:
    """Computes Hull MA and MACD incrementally from a candle stream.

    Usage:
        indicators = StreamingIndicators()
        initial = indicators.seed(historical_df, prior_close)
        # initial contains full series for chart backfill

        # Then for each live candle:
        point = indicators.update(close_price, candle_time)
        # point contains one HMA + MACD data point
    """

    def __init__(
        self,
        hull_length: int = 20,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
    ) -> None:
        self.hull_length = hull_length
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

        self.hull_state: HullState | None = None
        self.macd_state: MacdState | None = None
        self.seeded = False

    def seed(
        self,
        df: pl.DataFrame,
        prior_close: float | None = None,
    ) -> dict:
        """Seed indicators from historical candle data.

        Returns the full computed series as lists for chart backfill.
        Also initializes rolling state for subsequent update() calls.
        """
        if df.is_empty():
            return {"hma": [], "macd": []}

        pad = prior_close if prior_close is not None else float(df["close"][0])

        # Compute full Hull series
        hull_df = hull(df, length=self.hull_length, pad_value=pad)

        # Compute full MACD series
        macd_df = macd(
            df,
            prior_close=prior_close,
            fast_length=self.macd_fast,
            slow_length=self.macd_slow,
            macd_length=self.macd_signal,
        )

        # Initialize Hull rolling state from the tail of the data
        close_values = df["close"].to_list()
        self.hull_state = HullState(
            length=self.hull_length,
            pad_value=pad,
        )
        # Keep enough history for the largest window
        max_window = max(
            self.hull_length,
            self.hull_state.half_length,
            self.hull_state.sqrt_length,
        )
        self.hull_state.wma_full_window = close_values[-max_window:]
        self.hull_state.wma_half_window = close_values[-max_window:]

        # Recompute the diff series tail for the sqrt WMA window
        half_len = self.hull_state.half_length
        full_len = self.hull_length
        sqrt_len = self.hull_state.sqrt_length
        tail = (
            close_values[-(max_window + sqrt_len) :]
            if len(close_values) > max_window + sqrt_len
            else close_values
        )
        tail_np = np.array(tail, dtype=float)
        wma_h = padded_wma(tail_np, half_len, pad)
        wma_f = padded_wma(tail_np, full_len, pad)
        diff_series = 2 * wma_h - wma_f
        self.hull_state.wma_sqrt_window = diff_series[-sqrt_len:].tolist()

        # Store last HMA for color determination
        hma_values = hull_df["HMA"].to_list()
        self.hull_state.prev_hma = hma_values[-1] if hma_values else pad

        # Initialize MACD rolling state from the tail
        self.macd_state = MacdState(
            fast_length=self.macd_fast,
            slow_length=self.macd_slow,
            macd_length=self.macd_signal,
        )

        # Recompute EMA state by running through all values
        close_np = df["close"].to_numpy().astype(float)
        seed_val = prior_close if prior_close is not None else float(close_np[0])
        fast_ema = ema_with_seed(close_np, self.macd_fast, seed_val)
        slow_ema = ema_with_seed(close_np, self.macd_slow, seed_val)
        value_line = fast_ema - slow_ema
        signal_line = ema_with_seed(value_line, self.macd_signal, 0.0)
        histogram = value_line - signal_line

        self.macd_state.fast_ema = float(fast_ema[-1])
        self.macd_state.slow_ema = float(slow_ema[-1])
        self.macd_state.signal_ema = float(signal_line[-1])
        self.macd_state.prev_histogram = float(histogram[-1])

        self.seeded = True

        # Build response series
        # InfluxDB returns naive UTC datetimes — must mark as UTC before .timestamp()
        def to_utc_epoch(t: datetime) -> int:
            if t.tzinfo is None:
                return int(t.replace(tzinfo=timezone.utc).timestamp())
            return int(t.timestamp())

        hma_series = []
        for i in range(hull_df.height):
            hma_series.append(
                {
                    "time": to_utc_epoch(hull_df["time"][i]),
                    "value": round(float(hull_df["HMA"][i]), 4),
                    "color": "#01ffff"
                    if hull_df["HMA_color"][i] == "Up"
                    else "#ff66fe",
                }
            )

        macd_series = []
        for i in range(macd_df.height):
            t = to_utc_epoch(macd_df["time"][i])
            macd_series.append(
                {
                    "time": t,
                    "value": round(float(macd_df["Value"][i]), 6),
                    "signal": round(float(macd_df["avg"][i]), 6),
                    "histogram": round(float(macd_df["diff"][i]), 6),
                    "histogramColor": str(macd_df["diff_color"][i]),
                }
            )

        return {"hma": hma_series, "macd": macd_series}

    def update(self, close: float, time_epoch: int) -> dict | None:
        """Process one new candle close and return indicator deltas.

        Returns None if not yet seeded.
        """
        if not self.seeded or self.hull_state is None or self.macd_state is None:
            return None

        # --- Hull MA update ---
        hs = self.hull_state

        # Update the close windows
        hs.wma_full_window.append(close)
        hs.wma_half_window.append(close)
        # Trim to max needed size
        max_keep = max(hs.length, hs.half_length) + 10
        if len(hs.wma_full_window) > max_keep:
            hs.wma_full_window = hs.wma_full_window[-max_keep:]
            hs.wma_half_window = hs.wma_half_window[-max_keep:]

        # Compute current WMAs
        wma_half = compute_wma(hs.wma_half_window, hs.half_length)
        wma_full = compute_wma(hs.wma_full_window, hs.length)
        diff_val = 2 * wma_half - wma_full

        # Update sqrt window
        hs.wma_sqrt_window.append(diff_val)
        if len(hs.wma_sqrt_window) > hs.sqrt_length + 5:
            hs.wma_sqrt_window = hs.wma_sqrt_window[-(hs.sqrt_length + 5) :]

        hma_val = compute_wma(hs.wma_sqrt_window, hs.sqrt_length)
        hma_color = "#01ffff" if hma_val > (hs.prev_hma or 0) else "#ff66fe"
        hs.prev_hma = hma_val

        # --- MACD update ---
        ms = self.macd_state
        fast_alpha = 2.0 / (ms.fast_length + 1.0)
        slow_alpha = 2.0 / (ms.slow_length + 1.0)
        signal_alpha = 2.0 / (ms.macd_length + 1.0)

        ms.fast_ema = fast_alpha * close + (1 - fast_alpha) * ms.fast_ema
        ms.slow_ema = slow_alpha * close + (1 - slow_alpha) * ms.slow_ema
        macd_value = ms.fast_ema - ms.slow_ema
        ms.signal_ema = signal_alpha * macd_value + (1 - signal_alpha) * ms.signal_ema
        histogram = macd_value - ms.signal_ema

        # 4-shade histogram color
        if histogram > 0:
            hist_color = "#04FE00" if histogram > ms.prev_histogram else "#006401"
        else:
            hist_color = "#FE0000" if histogram < ms.prev_histogram else "#7E0100"
        ms.prev_histogram = histogram

        return {
            "hma": {
                "time": time_epoch,
                "value": round(hma_val, 4),
                "color": hma_color,
            },
            "macd": {
                "time": time_epoch,
                "value": round(macd_value, 6),
                "signal": round(ms.signal_ema, 6),
                "histogram": round(histogram, 6),
                "histogramColor": hist_color,
            },
        }
