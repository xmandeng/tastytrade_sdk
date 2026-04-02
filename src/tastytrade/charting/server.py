"""HTTP + WebSocket server for live charting.

Thin data pass-through: queries InfluxDB for history, bridges Redis
pub/sub events to the browser via WebSocket. Does not compute levels
or write back to any data store.
"""

import asyncio
import json
import logging
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from influxdb_client import InfluxDBClient

from tastytrade.charting.feed import ChartFeed
from tastytrade.charting.indicators import StreamingIndicators
from tastytrade.config.manager import RedisConfigManager
from tastytrade.providers.market import MarketDataProvider
from tastytrade.providers.subscriptions import RedisSubscription

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
ET = ZoneInfo("America/New_York")


def utc_epoch_to_et_epoch(utc_epoch: int) -> int:
    """Convert a UTC epoch to an ET-shifted epoch for lightweight-charts display.

    lightweight-charts always displays timestamps as-is (no timezone support).
    To show ET times, we shift the epoch by the ET offset so the displayed
    time matches Eastern Time.
    """
    utc_dt = datetime.fromtimestamp(utc_epoch, tz=timezone.utc)
    et_dt = utc_dt.astimezone(ET)
    # Get the UTC offset in seconds and add it to the epoch
    offset_seconds = int(et_dt.utcoffset().total_seconds())  # type: ignore[union-attr]
    return utc_epoch + offset_seconds


def naive_utc_to_epoch(t: datetime) -> int:
    """Convert a naive UTC datetime (from InfluxDB) to a proper UTC epoch.

    InfluxDB returns naive datetimes that are in UTC. Python's .timestamp()
    treats naive datetimes as LOCAL time, which is wrong when the server
    runs in a non-UTC timezone (e.g., EDT). This function explicitly treats
    the naive datetime as UTC.
    """
    if t.tzinfo is None:
        return int(t.replace(tzinfo=timezone.utc).timestamp())
    return int(t.timestamp())


def build_candle_payload(df: pl.DataFrame) -> list[dict[str, Any]]:
    """Convert a Polars candle DataFrame to lightweight-charts format with ET times."""
    candles = []
    for row in df.iter_rows(named=True):
        t = row.get("time")
        if t is None:
            continue
        if row.get("close") is None or row.get("close") == 0:
            continue
        utc_epoch = naive_utc_to_epoch(t) if isinstance(t, datetime) else int(t)
        et_epoch = utc_epoch_to_et_epoch(utc_epoch)
        candles.append(
            {
                "time": et_epoch,
                "open": round(float(row.get("open", 0)), 4),
                "high": round(float(row.get("high", 0)), 4),
                "low": round(float(row.get("low", 0)), 4),
                "close": round(float(row.get("close", 0)), 4),
            }
        )
    return candles


def find_last_trading_day(from_date: date_type, max_lookback: int = 7) -> date_type:
    """Walk backwards from from_date to find the last weekday.

    Used only for prior day candle lookups (equities don't have daily
    candles on weekends). For the chart date itself, use
    find_date_with_data() which tries today first (works for crypto/futures).
    """
    d = from_date
    for _ in range(max_lookback):
        if d.weekday() < 5:  # Mon-Fri
            return d
        d -= timedelta(days=1)
    return from_date


class ChartServer:
    """Live chart server combining InfluxDB history with Redis live feed."""

    def __init__(
        self,
        symbol: str = "SPX",
        interval: str = "m",
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.host = host
        self.port = port
        self.app = self.create_app()

    def create_app(self) -> FastAPI:
        app = FastAPI(title="tasty-chart")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(
                STATIC_DIR / "index.html",
                headers={"Cache-Control": "no-cache"},
            )

        @app.get("/api/config")
        async def config() -> dict:
            return {"symbol": self.symbol, "interval": self.interval}

        @app.get("/api/symbols")
        async def symbols() -> dict:
            """Return deduplicated base symbols from active subscriptions."""
            from tastytrade.connections.subscription import (
                RedisSubscriptionStore,
            )

            store = RedisSubscriptionStore()
            try:
                await store.initialize()
                subs = await store.get_active_subscriptions()
                base = {sym.split("{=")[0] for sym in subs if "{=" in sym}
                return {"symbols": sorted(base)}
            except Exception:
                logger.exception("Failed to fetch symbols")
                return {"symbols": []}
            finally:
                await store.redis.close()  # type: ignore[union-attr]

        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket) -> None:
            await ws.accept(subprotocol=None)
            symbol = ws.query_params.get("symbol", self.symbol)
            interval = ws.query_params.get("interval", self.interval)
            chart_date = ws.query_params.get("date")

            try:
                await self.handle_chart_session(ws, symbol, interval, chart_date)
            except WebSocketDisconnect:
                logger.info("Chart client disconnected for %s", symbol)
            except Exception:
                logger.exception("Chart session error for %s", symbol)
                try:
                    await ws.close(code=1011)
                except Exception:
                    pass

        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        return app

    async def handle_chart_session(
        self,
        ws: WebSocket,
        symbol: str,
        interval: str,
        chart_date: str | None = None,
    ) -> None:
        """Handle a single chart WebSocket session."""
        config = RedisConfigManager()

        influx_url = config.get("INFLUX_DB_URL", "http://localhost:8086")
        influx_token = config.get("INFLUX_DB_TOKEN")
        influx_org = config.get("INFLUX_DB_ORG")

        if not influx_token or not influx_org:
            await ws.send_json({"type": "error", "message": "InfluxDB not configured"})
            return

        influx_client = InfluxDBClient(
            url=influx_url, token=influx_token, org=influx_org
        )
        data_sub = RedisSubscription(config)
        provider = MarketDataProvider(data_feed=data_sub, influx=influx_client)

        candle_symbol = f"{symbol}{{={interval}}}"

        # Determine which trading day to display.
        # Try the requested date (or today) first. If no data, walk back up to 5 days.
        # This handles crypto (24/7), Sunday evening futures, and weekday equities.
        if chart_date:
            try:
                target_date = date_type.fromisoformat(chart_date)
            except ValueError:
                target_date = date_type.today()
        else:
            target_date = date_type.today()

        prior_date = find_last_trading_day(target_date - timedelta(days=1))

        logger.info(
            "Chart session: symbol=%r candle=%r date=%s prior=%s",
            symbol,
            candle_symbol,
            target_date,
            prior_date,
        )

        # --- Fetch single day of candles (ET day boundaries) ---
        # Try the target date. If no data, walk back up to 5 days.
        hist_df = None
        for attempt in range(6):
            d = target_date - timedelta(days=attempt)
            et_start = datetime(d.year, d.month, d.day, tzinfo=ET)
            et_stop = et_start + timedelta(days=1)
            utc_start = et_start.astimezone(timezone.utc).replace(tzinfo=None)
            utc_stop = et_stop.astimezone(timezone.utc).replace(tzinfo=None)

            logger.info(
                "Trying: symbol=%r ET=%s UTC=%s..%s",
                candle_symbol,
                d,
                utc_start,
                utc_stop,
            )
            hist_df = provider.download(
                symbol=candle_symbol,
                start=utc_start,
                stop=utc_stop,
                debug_mode=True,
            )
            if hist_df is not None and not hist_df.is_empty():
                target_date = d
                prior_date = find_last_trading_day(d - timedelta(days=1))
                break
            hist_df = None

        if hist_df is None:
            await ws.send_json(
                {
                    "type": "error",
                    "message": f"No data for {candle_symbol} in the last 6 days",
                }
            )
            influx_client.close()
            return

        # Filter zero-price rows
        before_count = hist_df.height
        hist_df = hist_df.filter(
            (pl.col("close").is_not_null()) & (pl.col("close") != 0)
        ).sort("time")
        removed = before_count - hist_df.height
        if removed > 0:
            logger.info(
                "Removed %d zero-price rows from %d total", removed, before_count
            )

        # --- Prior day candle for levels + indicator seeding ---
        prior_close: float | None = None
        daily_candle: dict[str, float | None] | None = None
        try:
            prior_day = provider.get_daily_candle(symbol, prior_date)
            prior_close = float(prior_day.close) if prior_day.close else None
            daily_candle = {
                "close": prior_close,
                "high": float(prior_day.high) if prior_day.high else None,
                "low": float(prior_day.low) if prior_day.low else None,
            }
            logger.info("Prior day close for %s: %s", symbol, prior_close)
        except Exception:
            logger.warning("Could not fetch prior day candle for %s", symbol)

        # --- Compute indicators ---
        indicators = StreamingIndicators()
        indicator_data = indicators.seed(hist_df, prior_close)

        # --- Build payload with ET-converted timestamps ---
        candles = build_candle_payload(hist_df)

        # Convert indicator timestamps to ET
        for point in indicator_data["hma"]:
            point["time"] = utc_epoch_to_et_epoch(point["time"])
        for point in indicator_data["macd"]:
            point["time"] = utc_epoch_to_et_epoch(point["time"])

        initial_payload = {
            "type": "init",
            "symbol": symbol,
            "interval": interval,
            "date": target_date.isoformat(),
            "candles": candles,
            "hma": indicator_data["hma"],
            "macd": indicator_data["macd"],
            "dailyCandle": daily_candle,
        }

        await ws.send_text(json.dumps(initial_payload))
        logger.info(
            "Sent %s %s: %d candles, %d HMA, %d MACD",
            symbol,
            target_date,
            len(candles),
            len(indicator_data["hma"]),
            len(indicator_data["macd"]),
        )

        # --- Phase 2: Live updates from Redis ---
        feed = ChartFeed(config)
        live_task = asyncio.create_task(
            self.stream_live_updates(ws, feed, indicators, symbol, interval)
        )

        # Monitor WebSocket for client disconnect so the feed task is cancelled
        # promptly instead of blocking on Redis pub/sub until the next message.
        async def wait_for_disconnect() -> None:
            try:
                while True:
                    await ws.receive_text()
            except (WebSocketDisconnect, Exception):
                pass

        disconnect_task = asyncio.create_task(wait_for_disconnect())

        try:
            done, pending = await asyncio.wait(
                [live_task, disconnect_task], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
        except asyncio.CancelledError:
            pass
        finally:
            await feed.close()
            influx_client.close()

    async def stream_live_updates(
        self,
        ws: WebSocket,
        feed: ChartFeed,
        indicators: StreamingIndicators,
        symbol: str,
        interval: str,
    ) -> None:
        """Subscribe to Redis and stream deltas to the WebSocket client.

        DXLink sends multiple events per candle period (every tick updates
        the current candle's OHLC).  Indicators must only advance once per
        period — when a NEW candle timestamp appears — using the final close
        of the *previous* candle.  Otherwise HMA windows fill with duplicate
        values and MACD EMAs are over-updated, causing both to diverge.
        """
        candle_symbol = f"{symbol}{{={interval}}}"
        prev_candle_epoch: int = 0
        prev_candle_close: float = 0.0

        async for event_type, event in feed.listen(symbol, candle_symbol):
            if event_type == "candle":
                raw_close = event.get("close")
                t = event.get("time")
                if raw_close is None or t is None:
                    continue
                close = float(raw_close)
                if close == 0:
                    continue

                utc_epoch = (
                    int(t)
                    if isinstance(t, (int, float))
                    else int(datetime.fromisoformat(str(t)).timestamp())
                )
                et_epoch = utc_epoch_to_et_epoch(utc_epoch)

                candle_msg = {
                    "time": et_epoch,
                    "open": round(float(event.get("open") or 0), 4),
                    "high": round(float(event.get("high") or 0), 4),
                    "low": round(float(event.get("low") or 0), 4),
                    "close": round(close, 4),
                }

                delta: dict[str, Any] = {"type": "update", "candle": candle_msg}

                # Only advance indicators when a new candle period starts.
                # Use the final close of the *previous* candle for accuracy.
                if prev_candle_epoch != 0 and et_epoch != prev_candle_epoch:
                    indicator_point = indicators.update(
                        prev_candle_close,
                        prev_candle_epoch,
                    )
                    if indicator_point:
                        delta["hma"] = indicator_point["hma"]
                        delta["macd"] = indicator_point["macd"]

                prev_candle_epoch = et_epoch
                prev_candle_close = close

                await ws.send_text(json.dumps(delta))

            elif event_type == "level":
                level_msg = {
                    "type": "level",
                    "price": float(event.get("price", 0)),
                    "label": event.get("label", ""),
                    "color": event.get("color", "#ffffff"),
                    "lineStyle": event.get("line_dash", "solid"),
                    "opacity": float(event.get("opacity", 0.7)),
                }
                await ws.send_text(json.dumps(level_msg))

    async def start(self, port: int | None = None) -> None:
        """Start the chart server."""
        p = port or self.port
        config = uvicorn.Config(self.app, host=self.host, port=p, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
