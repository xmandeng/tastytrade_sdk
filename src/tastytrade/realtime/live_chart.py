"""Library-provided live streaming MACD + Hull chart utilities.

Features:
    * Bootstrap historical slice (minimum rows with automatic fallback)
    * Event-driven updates (listener) where available; fallback to lightweight polling
    * Incremental MACD + Hull extensions leveraging RealTimeMACDHullChart
    * Simple start/stop lifecycle for notebooks or scripts
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from ..analytics.visualizations.realtime import RealTimeMACDHullChart
from .notebook import (
    register_candle_listener,
    setup_realtime_chart,
    start_chart_stream_task,
)


@dataclass
class LiveMACDHullStreamer:
    symbol: str
    interval: str = "5m"
    min_rows: int = 40
    fallback_min_rows: int = 8
    retries: int = 3
    poll_secs: float = 1.0
    hma_length: int = 20
    auto_display: bool = True  # attempt to auto-display figure in notebook
    on_status: Optional[Callable[[str], None]] = None
    _chart: Optional[RealTimeMACDHullChart] = None
    _task: Optional[asyncio.Task] = None
    _event_listener_attached: bool = False

    def _emit(self, msg: str):
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    async def start(self, dxlink) -> RealTimeMACDHullChart:
        if self._chart is not None:
            self._emit("chart already started")
            return self._chart

        attempt = 0
        target_rows = self.min_rows
        last_err: Exception | None = None
        while attempt <= self.retries:
            try:
                self._emit(f"bootstrap attempt {attempt + 1} (min_rows={target_rows})")
                self._chart = await setup_realtime_chart(
                    dxlink,
                    self.symbol,
                    interval=self.interval,
                    min_rows=target_rows,
                    hma_length=self.hma_length,
                )
                break
            except Exception as e:  # noqa: BLE001 broad to continue fallback
                last_err = e
                attempt += 1
                if target_rows > self.fallback_min_rows:
                    target_rows = max(self.fallback_min_rows, target_rows // 2)
                else:
                    await asyncio.sleep(1.0)
        if self._chart is None:
            raise RuntimeError(
                f"Failed to bootstrap live chart after {self.retries} retries: {last_err}"
            )

        self._chart.figure.update_layout(
            title=f"{self.symbol} {self.interval} — Live MACD + Hull"
        )

        # Auto-display for Jupyter / VSCode notebooks if requested
        if self.auto_display:
            try:  # defer import to avoid hard dependency outside notebooks
                from IPython.display import display  # type: ignore

                display(self._chart.figure)
            except Exception:  # noqa: BLE001
                pass

        # Prefer event-driven listener
        def _on_candle(ev):  # type: ignore[no-untyped-def]
            try:
                self._chart.add_candle(ev)
            except Exception as exc:  # noqa: BLE001
                self._emit(f"update error: {exc}")

        attached = register_candle_listener(
            dxlink, self.symbol, self.interval, _on_candle
        )
        self._event_listener_attached = attached
        if attached:
            self._emit("event-driven updates attached")
        else:
            self._emit("listener not supported; falling back to polling task")
            self._task = start_chart_stream_task(
                dxlink,
                self._chart,
                self.symbol,
                interval=self.interval,
                poll_secs=self.poll_secs,
            )
        return self._chart

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._chart = None
        self._event_listener_attached = False

    @property
    def figure(self):  # convenience access
        return self._chart.figure if self._chart else None


__all__ = ["LiveMACDHullStreamer"]
