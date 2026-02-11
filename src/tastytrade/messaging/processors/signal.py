"""Event processor that routes CandleEvent to a SignalEngine.

Attach to the Candle EventHandler. Other event types are ignored,
including TradeSignal (prevents re-entrant loops when signals are
emitted back into the processor chain).
"""

import logging
from typing import Callable

from tastytrade.analytics.engines.protocol import SignalEngine
from tastytrade.messaging.models.events import BaseEvent, CandleEvent

logger = logging.getLogger(__name__)


class SignalEventProcessor:
    """Routes CandleEvent to a SignalEngine and emits TradeSignal via callback.

    Implements the EventProcessor protocol (name, process_event, close).
    Should be attached to the Candle EventHandler.
    """

    name: str = "signal"

    def __init__(
        self,
        engine: SignalEngine,
        emit: Callable[[BaseEvent], None] | None = None,
    ) -> None:
        self.engine = engine
        self._emit = emit
        self._signal_count = 0

        def on_signal_fired(signal: BaseEvent) -> None:
            self._signal_count += 1
            if self._emit:
                self._emit(signal)

        self.engine.on_signal = on_signal_fired  # type: ignore[assignment]

    def process_event(self, event: BaseEvent) -> None:
        if isinstance(event, CandleEvent):
            self.engine.on_candle_event(event)

    def close(self) -> None:
        logger.info(
            "SignalEventProcessor closing — %d signals emitted", self._signal_count
        )
