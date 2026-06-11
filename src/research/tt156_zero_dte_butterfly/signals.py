"""Live Hull/MACD signal generation for the research day.

Runs the production HullMacdEngine in-process: warmed up from InfluxDB
history (MACD(26) on 5m bars needs hours of context a 9:30 cold start
would lack), then fed live from the Redis candle channels published by
the already-running subscribe service.
"""

import logging
import threading
from datetime import date, datetime, timedelta

from tastytrade.analytics.engines.hull_macd import HullMacdEngine
from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.config import RedisConfigManager
from tastytrade.messaging.models.events import BaseEvent, CandleEvent
from tastytrade.providers.market import MarketDataProvider
from tastytrade.providers.subscriptions import RedisSubscription
from tastytrade.utils.time_series import initialize_influx_client

from research.tt156_zero_dte_butterfly.config import SYMBOL

logger = logging.getLogger(__name__)

INTERVALS = ("m", "5m")


class SignalCapture:
    """EventPublisher that collects TradeSignals for in-process consumption.

    The Redis listener fires callbacks from the event loop while the
    collector drains from its sampling loop — guard with a lock.
    """

    def __init__(self) -> None:
        self.captured: list[TradeSignal] = []
        self.lock = threading.Lock()

    def publish(self, event: BaseEvent) -> None:
        if isinstance(event, TradeSignal):
            with self.lock:
                self.captured.append(event)

    def drain(self) -> list[TradeSignal]:
        with self.lock:
            signals = self.captured[:]
            self.captured.clear()
        return signals


class LiveSignalEngine:
    """HullMacdEngine wrapper: InfluxDB warmup, live Redis feed, spot tracking."""

    def __init__(self, warmup_days: int = 3) -> None:
        self.capture = SignalCapture()
        self.engine = HullMacdEngine(publisher=self.capture)
        self.warmup_days = warmup_days
        self.latest_spot: float | None = None
        self.latest_spot_time: datetime | None = None
        self.subscription: RedisSubscription | None = None

    def candle_symbols(self) -> list[str]:
        return [f"{SYMBOL}{{={interval}}}" for interval in INTERVALS]

    def warmup(self, session_date: date) -> None:
        """Replay recent history from InfluxDB through the engine."""
        influx = initialize_influx_client()
        provider = MarketDataProvider(
            data_feed=RedisSubscription(RedisConfigManager()), influx=influx
        )

        prior = provider.get_daily_candle(SYMBOL, session_date - timedelta(days=1))
        prior_close = float(prior.close) if prior.close is not None else None
        logger.info("Prior session close: %s", prior_close)

        for symbol in self.candle_symbols():
            if prior_close is not None:
                self.engine.set_prior_close(symbol, prior_close)
            df = provider.download(
                symbol=symbol,
                start=session_date - timedelta(days=self.warmup_days),
                stop=session_date,
            )
            count = 0
            for row in df.sort("time").to_dicts():
                try:
                    self.engine.on_candle_event(CandleEvent(**row))
                    count += 1
                except Exception:
                    continue
            logger.info("Warmup replayed %d candles for %s", count, symbol)

        warmup_signals = len(self.capture.drain())
        logger.info("Discarded %d warmup signals", warmup_signals)
        # Warmup replay leaves yesterday's position flags set; today's book
        # starts flat, so reset the state machine but keep the candle history.
        for state in self.engine._states.values():  # noqa: SLF001 — no public accessor
            state.bullish_open = False
            state.bearish_open = False
            state.hull_armed_direction = None
            state.macd_armed_direction = None
        influx.close()

    async def start_live(self) -> None:
        """Subscribe to the live Redis candle channels."""
        self.subscription = RedisSubscription(RedisConfigManager())
        await self.subscription.connect()
        for symbol in self.candle_symbols():
            await self.subscription.subscribe(
                f"market:CandleEvent:{symbol}",
                event_type=CandleEvent,
                on_update=self.on_candle,
            )

    def on_candle(self, event: BaseEvent) -> None:
        if not isinstance(event, CandleEvent):
            return
        if event.eventSymbol == f"{SYMBOL}{{=m}}" and event.close is not None:
            self.latest_spot = float(event.close)
            self.latest_spot_time = event.time
        self.engine.on_candle_event(event)

    def state_summary(self) -> dict[str, dict[str, str | bool | None]]:
        summary: dict[str, dict[str, str | bool | None]] = {}
        for symbol, state in self.engine._states.items():  # noqa: SLF001
            summary[symbol] = {
                "hull_direction": state.hull_direction,
                "macd_position": state.macd_position,
                "hull_armed": state.hull_armed_direction,
                "macd_armed": state.macd_armed_direction,
                "bullish_open": state.bullish_open,
                "bearish_open": state.bearish_open,
            }
        return summary

    async def close(self) -> None:
        if self.subscription is not None:
            await self.subscription.close()
