"""BacktestRunner — multi-timeframe engine runner for backtesting.

Subscribes to Redis channels for both signal-timeframe and
pricing-timeframe candles.  Signal candles feed into the engine;
pricing candles are buffered by the BacktestPublisher for entry/exit
price enrichment.

Follows the same three-layer separation as the live EngineRunner:
    cli.py    → What to run (factory: config, engine, channels)
    runner.py → How to run (wire subscriptions, manage lifecycle)
    engine    → The work (pure state machine: event in, signal out)
"""

import logging

from tastytrade.analytics.engines.protocol import SignalEngine
from tastytrade.backtest.models import BacktestConfig, BacktestSignal
from tastytrade.backtest.publisher import BacktestPublisher
from tastytrade.messaging.models.events import CandleEvent
from tastytrade.providers.subscriptions import RedisSubscription

logger = logging.getLogger(__name__)


class BacktestRunner:
    """Multi-timeframe backtest engine runner.

    Subscribes to Redis channels for both signal-timeframe and
    pricing-timeframe candles.  Signal candles feed into the engine.
    Pricing candles are buffered for entry/exit price enrichment.

    The runner does NOT access InfluxDB directly — all data arrives
    via Redis pub/sub, matching the production architecture.
    """

    def __init__(
        self,
        config: BacktestConfig,
        subscription: RedisSubscription,
        engine: SignalEngine,
        publisher: BacktestPublisher,
    ) -> None:
        self._config = config
        self._subscription = subscription
        self._engine = engine
        self._publisher = publisher

    async def setup(self) -> None:
        """Connect and subscribe to Redis channels.

        Subscribes to signal-timeframe and pricing-timeframe channels.
        Must be called before the replay starts publishing candles.
        """
        await self._subscription.connect()

        signal_channel = f"backtest:CandleEvent:{self._config.signal_symbol}"

        await self._subscription.subscribe(
            signal_channel,
            event_type=CandleEvent,
            on_update=self._engine.on_candle_event,  # type: ignore[arg-type]
        )
        logger.info("BacktestRunner subscribed to signal channel: %s", signal_channel)

        # Subscribe to pricing-timeframe if different from signal
        if self._config.pricing_symbol != self._config.signal_symbol:
            pricing_channel = f"backtest:CandleEvent:{self._config.pricing_symbol}"
            await self._subscription.subscribe(
                pricing_channel,
                event_type=CandleEvent,
                on_update=self._publisher.buffer_pricing_candle,  # type: ignore[arg-type]
            )
            logger.info(
                "BacktestRunner subscribed to pricing channel: %s",
                pricing_channel,
            )

        logger.info(
            "BacktestRunner ready — backtest_id=%s, engine=%s, symbol=%s",
            self._config.backtest_id,
            self._engine.name,
            self._config.symbol,
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info(
            "BacktestRunner stopping — backtest_id=%s",
            self._config.backtest_id,
        )
        self._publisher.close()
        await self._subscription.close()
        logger.info(
            "BacktestRunner stopped — %d signals generated",
            len(self._publisher.signals),
        )

    @property
    def signals(self) -> list[BacktestSignal]:
        """All BacktestSignals generated during this run."""
        return self._publisher.signals
