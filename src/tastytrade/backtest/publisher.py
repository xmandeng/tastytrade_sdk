"""BacktestPublisher — EventPublisher that enriches signals with backtest metadata.

Implements the EventPublisher protocol so it can be wired directly into
any SignalEngine's publisher slot.  When the engine calls publish(signal),
this publisher:

1. Looks up the closest pricing-interval candle from its internal buffer
2. Creates a BacktestSignal with enriched pricing data
3. Publishes the BacktestSignal to Redis via the inner RedisPublisher

The pricing candle buffer is fed by the BacktestRunner, which subscribes
to the pricing-timeframe Redis channel separately.
"""

import logging
from datetime import datetime

from tastytrade.backtest.models import BacktestConfig, BacktestSignal
from tastytrade.messaging.models.events import BaseEvent, CandleEvent
from tastytrade.providers.subscriptions import RedisPublisher

logger = logging.getLogger(__name__)


class BacktestPublisher:
    """EventPublisher wrapper that enriches TradeSignal → BacktestSignal.

    Satisfies the EventPublisher protocol (structural subtyping) so
    HullMacdEngine can use it directly via its ``publisher`` slot.
    """

    def __init__(
        self,
        config: BacktestConfig,
        inner_publisher: RedisPublisher | None = None,
    ) -> None:
        self._config = config
        self._inner = inner_publisher
        self._pricing_candles: list[CandleEvent] = []
        self._signals: list[BacktestSignal] = []

    @property
    def signals(self) -> list[BacktestSignal]:
        """All BacktestSignals emitted during this run."""
        return self._signals

    def buffer_pricing_candle(self, candle: CandleEvent) -> None:
        """Buffer a pricing-interval candle for later lookup.

        Called by the BacktestRunner when a pricing-timeframe candle
        arrives on the Redis subscription.
        """
        self._pricing_candles.append(candle)

    def publish(self, event: BaseEvent) -> None:
        """Enrich TradeSignal → BacktestSignal, then publish to Redis.

        If the event is not a TradeSignal (or subclass), it is forwarded
        to the inner publisher unchanged.
        """
        from tastytrade.analytics.engines.models import TradeSignal

        if not isinstance(event, TradeSignal):
            if self._inner:
                self._inner.publish(event)
            return

        signal = event
        entry_price = self._find_entry_price(signal.start_time)

        backtest_signal = BacktestSignal(
            eventSymbol=signal.eventSymbol,
            start_time=signal.start_time,
            label=signal.label,
            color=signal.color,
            line_width=signal.line_width,
            line_dash=signal.line_dash,
            opacity=signal.opacity,
            signal_type=signal.signal_type,
            direction=signal.direction,
            engine=signal.engine,
            hull_direction=signal.hull_direction,
            hull_value=signal.hull_value,
            macd_value=signal.macd_value,
            macd_signal=signal.macd_signal,
            macd_histogram=signal.macd_histogram,
            close_price=signal.close_price,
            trigger=signal.trigger,
            backtest_id=self._config.backtest_id,
            source=self._config.source,
            entry_price=entry_price,
            signal_interval=self._config.signal_interval,
            pricing_interval=self._config.resolved_pricing_interval,
        )

        self._signals.append(backtest_signal)

        logger.info(
            "BacktestSignal: %s %s %s at %s (entry_price=%s)",
            backtest_signal.signal_type,
            backtest_signal.direction,
            backtest_signal.eventSymbol,
            backtest_signal.start_time.isoformat(),
            backtest_signal.entry_price,
        )

        if self._inner:
            self._inner.publish(backtest_signal)

    def _find_entry_price(self, signal_time: datetime) -> float | None:
        """Find the closest pricing-interval candle close price at signal time.

        Walks backward through the pricing buffer to find the most recent
        candle whose time is <= signal_time.
        """
        if not self._pricing_candles:
            return None

        best: CandleEvent | None = None
        for candle in reversed(self._pricing_candles):
            if candle.time <= signal_time and candle.close is not None:
                best = candle
                break

        return float(best.close) if best and best.close is not None else None

    def close(self) -> None:
        """Close the inner publisher if present."""
        if self._inner:
            self._inner.close()
