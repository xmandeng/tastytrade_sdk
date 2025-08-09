"""Realtime MACD + Hull Moving Average plotting utilities.

This module provides a lightweight, resource‑efficient pathway to render the
same figure composition produced by `plot_macd_with_hull` but in a *live*
streaming context (Jupyter or a web client later via WebSocket broadcast).

Design goals:
    * Minimal recomputation – MACD updated incrementally (O(1) per candle)
    * Hull MA recomputed over a bounded tail slice (cheap; length ~20 by default)
    * UI updates throttled (extend traces; avoid full relayout unless needed)
    * Clean separation of state (indicator state vs figure object)
    * Async friendly – a single `async for` loop consumes CandleEvents

Key classes:
    IncrementalMACDState – maintains EMA_fast, EMA_slow, EMA_signal & histogram color logic
    RealTimeMACDHullChart – encapsulates a Plotly FigureWidget + update API

Usage (Jupyter):
    chart = RealTimeMACDHullChart(prior_close=prev_close)
    chart.bootstrap(initial_candles_pl_df)  # historical warmup
    await stream_to_chart(streamer, symbol, chart)

Future extension points (not implemented yet):
    * FastAPI WebSocket push (serialize candles + incremental indicator values)
    * Backfill-in/gap detection & repair
    * Multiple timeframes overlay (e.g. 1m + 5m HMA)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from ...messaging.models.events import CandleEvent
from ..indicators.momentum import hull as full_hull
from ..indicators.momentum import macd as full_macd
from .plots import HorizontalLine, VerticalLine

# -------------------------------------------------------------------------------------------------
# Incremental MACD
# -------------------------------------------------------------------------------------------------


@dataclass
class IncrementalMACDState:
    """Maintain EMA state for incremental MACD updates."""

    prior_close: float
    fast_length: int = 12
    slow_length: int = 26
    macd_length: int = 9
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    ema_signal: Optional[float] = None
    last_hist: Optional[float] = None

    def _alpha(self, length: int) -> float:
        return 2.0 / (length + 1.0)

    def update(self, price: float) -> dict:
        # Seed fast/slow with prior_close if None
        if self.ema_fast is None:
            self.ema_fast = price if self.prior_close is None else self.prior_close
        if self.ema_slow is None:
            self.ema_slow = price if self.prior_close is None else self.prior_close

        a_fast = self._alpha(self.fast_length)
        a_slow = self._alpha(self.slow_length)
        self.ema_fast = a_fast * price + (1 - a_fast) * self.ema_fast
        self.ema_slow = a_slow * price + (1 - a_slow) * self.ema_slow

        value = self.ema_fast - self.ema_slow

        # Seed signal at 0.0 the first time
        if self.ema_signal is None:
            self.ema_signal = 0.0
        a_sig = self._alpha(self.macd_length)
        self.ema_signal = a_sig * value + (1 - a_sig) * self.ema_signal

        hist = value - self.ema_signal
        color = self._hist_color(hist)
        self.last_hist = hist

        return {
            "Value": value,
            "avg": self.ema_signal,
            "diff": hist,
            "diff_color": color,
        }

    def _hist_color(self, hist: float) -> str:
        prev = self.last_hist
        if prev is None:
            return "#04FE00" if hist > 0 else "#FE0000"
        if hist > 0:
            return "#04FE00" if hist > prev else "#006401"
        else:
            return "#FE0000" if hist < prev else "#7E0100"


# -------------------------------------------------------------------------------------------------
# Hull MA helper (simple bounded recompute strategy)
# -------------------------------------------------------------------------------------------------


class BoundedHull:
    """Recompute Hull MA on a tail slice each update (fast for small length)."""

    def __init__(
        self,
        length: int = 20,
        tail_window: Optional[int] = 2000,
        pad_value: Optional[float] = None,
    ):
        self.length = length
        self.tail_window = tail_window
        self.pad_value = pad_value

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if self.tail_window is not None and len(df) > self.tail_window:
            df_slice = df.tail(self.tail_window)
        else:
            df_slice = df
        return full_hull(df_slice, pad_value=self.pad_value)


# -------------------------------------------------------------------------------------------------
# Real-time chart container
# -------------------------------------------------------------------------------------------------


class RealTimeMACDHullChart:
    def __init__(
        self,
        prior_close: float,
        hma_length: int = 20,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        horizontal_lines: Optional[Sequence[HorizontalLine]] = None,
        vertical_lines: Optional[Sequence[VerticalLine]] = None,
        display_tz: str = "America/New_York",
        candle_interval: timedelta | None = None,
    ) -> None:
        self.prior_close = prior_close
        self.hma_calc = BoundedHull(length=hma_length, pad_value=prior_close)
        self.macd_state = IncrementalMACDState(
            prior_close=prior_close,
            fast_length=macd_fast,
            slow_length=macd_slow,
            macd_length=macd_signal,
        )
        self.horizontal_lines = list(horizontal_lines or [])
        self.vertical_lines = list(vertical_lines or [])
        self.display_tz = display_tz
        self.candle_interval: Optional[timedelta] = candle_interval

        # Data buffers
        self._df: Optional[pl.DataFrame] = None  # full candle history we manage
        # Display artifacts
        self._display_handle = (
            None  # will hold IPython display handle when FigureWidget unavailable
        )
        self._fig = self._build_base_figure()

    @property
    def figure(self):  # Plotly FigureWidget
        return self._fig

    def bootstrap(self, historical: pl.DataFrame) -> None:
        if historical.is_empty():
            raise ValueError("Historical bootstrap data cannot be empty")
        if self.candle_interval is None and len(historical) > 1:
            t0 = historical["time"][0]
            t1 = historical["time"][1]
            if isinstance(t0, datetime) and isinstance(t1, datetime):
                self.candle_interval = t1 - t0
        # Keep only rows with complete OHLC to ensure candlestick renders
        required_cols = ["open", "high", "low", "close"]
        have_cols = [c for c in required_cols if c in historical.columns]
        if len(have_cols) < 4:
            # Attempt to detect alternative naming (e.g., close_price) – basic heuristic
            rename_map = {}
            for alt, std in [
                ("close_price", "close"),
                ("open_price", "open"),
                ("high_price", "high"),
                ("low_price", "low"),
            ]:
                if alt in historical.columns and std not in historical.columns:
                    rename_map[alt] = std
            if rename_map:
                historical = historical.rename(rename_map)
        filtered = historical
        if {"open", "high", "low", "close"}.issubset(set(filtered.columns)):
            filtered = filtered.filter(
                pl.col("open").is_not_null()
                & pl.col("high").is_not_null()
                & pl.col("low").is_not_null()
                & pl.col("close").is_not_null()
            )
        if filtered.is_empty():
            # Fall back to original if filtering removed everything
            filtered = historical

        macd_full = full_macd(filtered, prior_close=self.prior_close)
        hma_df = self.hma_calc.compute(filtered)
        # Ensure polars DataFrame for join
        if (
            hasattr(hma_df, "__class__")
            and hma_df.__class__.__name__ == "DataFrame"
            and not isinstance(hma_df, pl.DataFrame)
        ):  # pandas DataFrame
            try:
                import pandas as _pd  # type: ignore

                if isinstance(hma_df, _pd.DataFrame):  # convert
                    hma_df = pl.from_pandas(hma_df)
            except Exception:  # noqa: BLE001
                pass
        self._df = macd_full.join(hma_df, on="time", how="left")
        self._render_full()
        # Fallback: if candlestick trace has zero points but we have data, add a simple line so user sees something
        try:
            cs = self._fig.data[0]
            if (len(getattr(cs, "x", []) or []) == 0) and not self._df.is_empty():
                # replace first trace with line
                import plotly.graph_objects as go  # local import

                with_nulls = self._df.select(["time", "close"]).to_pandas()
                with_nulls = with_nulls[with_nulls["close"].notna()]
                self._fig.data = tuple(
                    [
                        go.Scatter(
                            x=with_nulls["time"],
                            y=with_nulls["close"],
                            mode="lines",
                            line={"color": "#4CAF50", "width": 1},
                            name="Close",
                        )
                    ]
                    + list(self._fig.data[1:])
                )
        except Exception:  # noqa: BLE001
            pass

    def add_candle(self, candle: CandleEvent) -> None:
        if self._df is None:
            raise RuntimeError("Call bootstrap() first")
        if (
            candle.close is None
            or candle.open is None
            or candle.high is None
            or candle.low is None
        ):
            return

        ct = candle.time
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)

        append_new = True
        if self.candle_interval is not None and len(self._df) > 0:
            last_time = self._df["time"][-1]
            if isinstance(last_time, datetime):
                if ct < last_time + self.candle_interval:
                    append_new = False

        if append_new:
            new_row = pl.DataFrame(
                {
                    "time": [ct],
                    "open": [candle.open],
                    "high": [candle.high],
                    "low": [candle.low],
                    "close": [candle.close],
                    "volume": [candle.volume or 0.0],
                }
            )
            self._df = pl.concat(
                [
                    self._df.select(["time", "open", "high", "low", "close", "volume"]),
                    new_row,
                ]
            )
        else:
            base = self._df.select(
                ["time", "open", "high", "low", "close", "volume"]
            ).to_pandas()
            base.iloc[-1] = [
                ct,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume or 0.0,
            ]
            self._df = pl.from_pandas(base)

        macd_values = self.macd_state.update(candle.close)
        if "Value" not in self._df.columns:
            macd_full = full_macd(self._df, prior_close=self.prior_close)
            self._df = self._df.join(
                macd_full.select(["time", "Value", "avg", "diff", "diff_color"]),
                on="time",
                how="left",
            )
        else:
            df_pd = self._df.to_pandas()
            for k, v in macd_values.items():
                df_pd.loc[df_pd.index[-1], k] = v
            self._df = pl.from_pandas(df_pd)

        hma_df = self.hma_calc.compute(
            self._df.select(["time", "open", "high", "low", "close", "volume"])
        )
        if (
            hasattr(hma_df, "__class__")
            and hma_df.__class__.__name__ == "DataFrame"
            and not isinstance(hma_df, pl.DataFrame)
        ):
            try:
                import pandas as _pd  # type: ignore

                if isinstance(hma_df, _pd.DataFrame):
                    hma_df = pl.from_pandas(hma_df)
            except Exception:  # noqa: BLE001
                pass
        self._df = self._df.join(
            hma_df.select(["time", "HMA", "HMA_color"]), on="time", how="left"
        )

        self._extend_latest_traces()

    def _build_base_figure(self):
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.4, 0.2],
        )
        fig.add_trace(
            go.Candlestick(
                name="Price",
                showlegend=False,
                increasing_line_color="#4CAF50",
                decreasing_line_color="#EF5350",
                increasing_fillcolor="rgba(19,19,19,0.1)",
                decreasing_fillcolor="#EF5350",
                line_width=0.75,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                name="HMA",
                mode="lines",
                line={"color": "#01FFFF", "width": 0.6},
                showlegend=False,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                name="MACD (Value)",
                mode="lines",
                line={"color": "#01FFFF", "width": 1},
                showlegend=False,
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                name="Signal (avg)",
                mode="lines",
                line={"color": "#F8E9A6", "width": 1},
                showlegend=False,
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Bar(name="Histogram", marker_color=[], showlegend=False), row=2, col=1
        )
        fig.update_layout(
            template="plotly_dark",
            xaxis_rangeslider_visible=False,
            plot_bgcolor="rgb(25,25,25)",
            paper_bgcolor="rgb(25,25,25)",
        )
        # Wrap in FigureWidget for reactive notebook updates (so updating data arrays refreshes display)
        try:  # if ipywidgets available
            return go.FigureWidget(fig)
        except Exception:  # noqa: BLE001
            # Defer import to keep lightweight when running outside notebooks
            try:
                from IPython.display import display  # type: ignore

                self._display_handle = display(fig, display_id=True)
            except Exception:  # noqa: BLE001
                self._display_handle = None
            return fig  # fallback (we'll push manual updates via _render_full)

    def _render_full(self):
        assert self._df is not None
        df = self._df
        cs = self._fig.data[0]
        cs.update(
            x=df["time"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
        )
        hma_trace = self._fig.data[1]
        if "HMA" in df.columns:
            hma_trace.update(x=df["time"], y=df["HMA"])
        if {"Value", "avg", "diff"}.issubset(set(df.columns)):
            self._fig.data[2].update(x=df["time"], y=df["Value"])
            self._fig.data[3].update(x=df["time"], y=df["avg"])
            self._fig.data[4].update(
                x=df["time"], y=df["diff"], marker_color=df["diff_color"]
            )
        # If we are in fallback (non-FigureWidget) mode with a display handle, trigger an update
        if self._display_handle is not None:
            try:  # noqa: BLE001
                self._display_handle.update(self._fig)
            except Exception:
                pass

    def _extend_latest_traces(self):
        self._render_full()


async def stream_to_chart(
    streamer,
    symbol: str,
    chart: RealTimeMACDHullChart,
    warmup: int = 0,
    throttle_secs: float = 0.0,
    source_async_iterable=None,
):
    if source_async_iterable is None:
        raise NotImplementedError(
            "Provide source_async_iterable yielding CandleEvent objects."
        )

    async for event in source_async_iterable:
        if isinstance(event, CandleEvent):
            chart.add_candle(event)
            if throttle_secs:
                from asyncio import sleep

                await sleep(throttle_secs)


__all__ = [
    "IncrementalMACDState",
    "BoundedHull",
    "RealTimeMACDHullChart",
    "stream_to_chart",
]
