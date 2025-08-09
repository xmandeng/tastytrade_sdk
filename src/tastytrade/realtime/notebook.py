"""Notebook helper utilities for realtime charting.

Provides:
  * wait_for_candle_frame: Await until a candle frame for a symbol/interval is populated.
  * candle_event_stream: Async generator yielding newly completed/updated CandleEvent rows.
  * setup_realtime_chart: Bootstrap a RealTimeMACDHullChart from an existing frame.
  * start_chart_stream_task: Convenience to spawn background streaming task (Jupyter friendly).

These helpers allow notebooks to *import* production code instead of inlining indicator
and plotting logic, keeping business logic consolidated.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncGenerator, Optional

import polars as pl

from ..messaging.models.events import CandleEvent
from ..analytics.visualizations.realtime import RealTimeMACDHullChart


async def wait_for_candle_frame(
    dxlink,
    symbol: str,
    interval: str,
    min_rows: int = 10,
    poll_secs: float = 0.5,
    timeout: Optional[float] = 30.0,
) -> pl.DataFrame:
    """Poll until a candle frame with >= min_rows exists."""
    handler = (
        dxlink.router.handler[dxlink.router.subscription_channels.Candle].processors[
            "feed"
        ]
        if hasattr(dxlink.router, "subscription_channels")
        else dxlink.router.handler["Candle"].processors["feed"]
    )  # type: ignore[index]
    key = f"{symbol}{{={interval}}}"
    start = asyncio.get_running_loop().time()
    while True:
        frame = handler.frames.get(key)
        if frame is not None and not frame.is_empty() and len(frame) >= min_rows:
            return frame
        if (
            timeout is not None
            and (asyncio.get_running_loop().time() - start) > timeout
        ):
            raise TimeoutError(f"Timed out waiting for candle frame {key}")
        await asyncio.sleep(poll_secs)


audio = None  # placeholder for potential future audible alerts


async def candle_event_stream(
    dxlink,
    symbol: str,
    interval: str,
    poll_secs: float = 1.0,
) -> AsyncGenerator[CandleEvent, None]:
    """Yield new/updated CandleEvent rows for the specified symbol+interval."""
    handler = (
        dxlink.router.handler[dxlink.router.subscription_channels.Candle].processors[
            "feed"
        ]
        if hasattr(dxlink.router, "subscription_channels")
        else dxlink.router.handler["Candle"].processors["feed"]
    )  # type: ignore[index]
    key = f"{symbol}{{={interval}}}"
    last_dt: datetime | None = None
    while True:
        frame = handler.frames.get(key)
        if frame is not None and not frame.is_empty():
            row = frame.tail(1)
            try:
                ct = row["time"][0]
            except Exception:
                ct = datetime.utcnow()
            if last_dt is None or ct != last_dt:
                last_dt = ct
                candle = CandleEvent(
                    time=ct,
                    open=row.get_column("open")[0] if "open" in row.columns else None,
                    high=row.get_column("high")[0] if "high" in row.columns else None,
                    low=row.get_column("low")[0] if "low" in row.columns else None,
                    close=row.get_column("close")[0]
                    if "close" in row.columns
                    else None,
                    volume=row.get_column("volume")[0]
                    if "volume" in row.columns
                    else None,
                )
                yield candle
        await asyncio.sleep(poll_secs)


async def setup_realtime_chart(
    dxlink,
    symbol: str,
    interval: str = "5m",
    min_rows: int = 30,
    hma_length: int = 20,
) -> RealTimeMACDHullChart:
    """Bootstrap a realtime chart from existing frame data."""
    frame = await wait_for_candle_frame(dxlink, symbol, interval, min_rows=min_rows)
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    for col in missing:
        if col == "time":
            continue
        frame = frame.with_columns(pl.lit(None).alias(col))
    prior_close = (
        float(frame.select("close").tail(2)["close"][0])
        if len(frame) > 1
        else float(frame.select("close").tail(1)["close"][0])
    )
    chart = RealTimeMACDHullChart(prior_close=prior_close, hma_length=hma_length)
    chart.bootstrap(frame.select(["time", "open", "high", "low", "close", "volume"]))
    return chart


def start_chart_stream_task(
    dxlink,
    chart: RealTimeMACDHullChart,
    symbol: str,
    interval: str = "5m",
    poll_secs: float = 1.0,
) -> asyncio.Task:
    """Spawn background asyncio task to update chart with new candles."""

    async def _runner():
        async for candle in candle_event_stream(
            dxlink, symbol, interval, poll_secs=poll_secs
        ):
            chart.add_candle(candle)

    return asyncio.create_task(_runner(), name=f"chart-stream-{symbol}-{interval}")


__all__ = [
    "wait_for_candle_frame",
    "candle_event_stream",
    "setup_realtime_chart",
    "start_chart_stream_task",
]
