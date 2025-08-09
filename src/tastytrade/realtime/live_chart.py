"""Library-provided live streaming MACD + Hull chart utilities.

This wraps RealTimeMACDHullChart with an adapter that polls the candle frame
maintained by DXLink subscriptions and updates incrementally. Intended for
notebook/script use without duplicating logic in devtools.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from ..analytics.visualizations.realtime import RealTimeMACDHullChart
from .notebook import (
    setup_realtime_chart,
    start_chart_stream_task,
)


@dataclass
class LiveMACDHullStreamer:
    symbol: str
    interval: str = "5m"
    min_rows: int = 40
    poll_secs: float = 2.0
    hma_length: int = 20
    _chart: Optional[RealTimeMACDHullChart] = None
    _task: Optional[asyncio.Task] = None

    async def start(self, dxlink) -> RealTimeMACDHullChart:
        if self._chart is not None:
            return self._chart
        self._chart = await setup_realtime_chart(
            dxlink,
            self.symbol,
            interval=self.interval,
            min_rows=self.min_rows,
            hma_length=self.hma_length,
        )
        self._chart.figure.update_layout(
            title=f"{self.symbol} {self.interval} — Live MACD + Hull"
        )
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

    @property
    def figure(self):  # convenience access
        return self._chart.figure if self._chart else None


__all__ = ["LiveMACDHullStreamer"]
