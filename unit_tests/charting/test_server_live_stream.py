"""Tests for stream_live_updates client-disconnect handling (TT-166).

An abrupt client disconnect (keepalive ping timeout, no close frame) raises
WebSocketDisconnect from ws.send_text inside the live-update task. The task
must log one INFO line and finish cleanly — an unhandled raise is never
retrieved by the endpoint's asyncio.wait and spams the log with a
"Task exception was never retrieved" traceback.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from tastytrade.charting.feed import ChartFeed
from tastytrade.charting.indicators import StreamingIndicators
from tastytrade.charting.server import ChartServer

CANDLE = {
    "time": 1756645200,
    "open": 6499.0,
    "high": 6501.0,
    "low": 6498.5,
    "close": 6500.0,
}


def live_stream_args(send_text: AsyncMock) -> tuple[WebSocket, ChartFeed]:
    """Build a fake WebSocket and a feed yielding two candle events."""

    async def listen(
        symbol: str, candle_symbol: str
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        yield "candle", CANDLE
        yield "candle", {**CANDLE, "time": 1756645500}

    feed = MagicMock()
    feed.listen = listen
    ws = MagicMock()
    ws.send_text = send_text
    return cast(WebSocket, ws), cast(ChartFeed, feed)


@pytest.mark.asyncio
async def test_client_disconnect_logs_info_and_returns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    send_text = AsyncMock(side_effect=WebSocketDisconnect(code=1006))
    ws, feed = live_stream_args(send_text)
    server = ChartServer.__new__(ChartServer)

    with caplog.at_level(logging.INFO, logger="tastytrade.charting.server"):
        await server.stream_live_updates(ws, feed, StreamingIndicators(), "SPX", "5m")

    send_text.assert_awaited_once()  # loop must stop at the first failed send
    assert "disconnected during live stream" in caplog.text
    assert "SPX" in caplog.text


@pytest.mark.asyncio
async def test_unexpected_send_errors_still_propagate() -> None:
    # Only client disconnects are expected during streaming; anything else
    # must reach the endpoint's error handler, not be swallowed.
    send_text = AsyncMock(side_effect=RuntimeError("boom"))
    ws, feed = live_stream_args(send_text)
    server = ChartServer.__new__(ChartServer)

    with pytest.raises(RuntimeError):
        await server.stream_live_updates(ws, feed, StreamingIndicators(), "SPX", "5m")


@pytest.mark.asyncio
async def test_deltas_sent_for_each_candle() -> None:
    send_text = AsyncMock()
    ws, feed = live_stream_args(send_text)
    server = ChartServer.__new__(ChartServer)

    await server.stream_live_updates(ws, feed, StreamingIndicators(), "SPX", "5m")

    assert send_text.await_count == 2
