"""BacktestReplay — replays historical candles from InfluxDB to Redis.

Reads candle data for specified timeframes from InfluxDB via
MarketDataProvider, then publishes each candle to Redis on
``backtest:CandleEvent:*`` channels, interleaved chronologically
across timeframes.

This component runs on a server with InfluxDB access.  The
BacktestRunner (which may run on a separate server) subscribes
to these Redis channels — no direct InfluxDB dependency.
"""

import logging
import time as _time
from datetime import date, timedelta

import polars as pl

from tastytrade.backtest.models import BacktestConfig
from tastytrade.messaging.models.events import CandleEvent
from tastytrade.providers.market import MarketDataProvider

logger = logging.getLogger(__name__)


class BacktestReplay:
    """Replays historical candle data from InfluxDB to Redis.

    Downloads candles for signal-timeframe and pricing-timeframe,
    merges them chronologically, and publishes each candle to Redis
    on ``backtest:CandleEvent:{symbol}`` channels.
    """

    def __init__(
        self,
        config: BacktestConfig,
        provider: MarketDataProvider,
        redis_host: str | None = None,
        redis_port: int | None = None,
    ) -> None:
        import os

        import redis as sync_redis

        self._config = config
        self._provider = provider
        host: str = (
            redis_host
            if redis_host is not None
            else os.environ.get("REDIS_HOST", "localhost")
        )
        port: int = (
            redis_port
            if redis_port is not None
            else int(os.environ.get("REDIS_PORT", "6379"))
        )
        self._redis = sync_redis.Redis(host=host, port=port)

    def run(self) -> int:
        """Replay all candles and return count published.

        Downloads historical candles from InfluxDB, merges across
        timeframes sorted by time, and publishes each to Redis.
        """
        logger.info(
            "BacktestReplay starting — backtest_id=%s, symbol=%s, "
            "signal=%s, pricing=%s, range=%s to %s",
            self._config.backtest_id,
            self._config.symbol,
            self._config.signal_interval,
            self._config.resolved_pricing_interval,
            self._config.start_date,
            self._config.end_date,
        )

        # Add warmup buffer: fetch extra days before start_date for
        # indicator seeding (Hull needs ~20 candles, MACD needs ~26)
        warmup_start = self._config.start_date - timedelta(days=3)

        signal_df = self._download_candles(
            self._config.signal_symbol, warmup_start, self._config.end_date
        )

        pricing_df: pl.DataFrame | None = None
        if self._config.pricing_symbol != self._config.signal_symbol:
            pricing_df = self._download_candles(
                self._config.pricing_symbol,
                warmup_start,
                self._config.end_date,
            )

        candles = self._merge_and_sort(signal_df, pricing_df)

        count = 0
        for candle in candles:
            channel = f"backtest:CandleEvent:{candle.eventSymbol}"
            self._redis.publish(
                channel=channel,
                message=candle.model_dump_json(),
            )
            count += 1

            # Yield every 500 candles to avoid overwhelming Redis
            if count % 500 == 0:
                _time.sleep(0.01)

        logger.info(
            "BacktestReplay complete — %d candles published for %s",
            count,
            self._config.backtest_id,
        )
        return count

    def seed_prior_close(self) -> float | None:
        """Fetch the prior trading day's close for engine seeding.

        Returns the close price, or None if unavailable.
        """
        try:
            candle = self._provider.get_daily_candle(
                self._config.symbol,
                self._config.start_date - timedelta(days=1),
            )
            return float(candle.close) if candle.close is not None else None
        except (ValueError, Exception) as e:
            logger.warning("Could not fetch prior close: %s", e)
            return None

    def _download_candles(self, symbol: str, start: date, end: date) -> pl.DataFrame:
        """Download candles from InfluxDB via MarketDataProvider."""
        try:
            df = self._provider.download(
                symbol=symbol,
                start=start,
                stop=end,
                debug_mode=True,
            )
            logger.info(
                "Downloaded %d candles for %s (%s to %s)",
                df.height,
                symbol,
                start,
                end,
            )
            return df
        except Exception as e:
            logger.error("Failed to download candles for %s: %s", symbol, e)
            return pl.DataFrame()

    def _merge_and_sort(
        self,
        signal_df: pl.DataFrame,
        pricing_df: pl.DataFrame | None,
    ) -> list[CandleEvent]:
        """Merge candle DataFrames and sort chronologically.

        Pricing candles are interleaved BEFORE signal candles at the
        same timestamp, so the pricing buffer is populated before the
        engine processes the signal-timeframe candle.
        """
        candles: list[CandleEvent] = []

        for row in signal_df.to_dicts():
            try:
                candles.append(CandleEvent(**row))
            except Exception:
                continue

        if pricing_df is not None:
            for row in pricing_df.to_dicts():
                try:
                    candles.append(CandleEvent(**row))
                except Exception:
                    continue

        # Sort by time. For candles at the same time, pricing-interval
        # candles should come first (they have the shorter interval in
        # the eventSymbol, which sorts lexicographically earlier).
        candles.sort(key=lambda c: c.time)
        return candles

    def close(self) -> None:
        """Close the Redis connection."""
        self._redis.close()
