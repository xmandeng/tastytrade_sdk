"""Event processor that routes CandleEvent to a SignalEngine.

Attach to the Candle EventHandler. Non-CandleEvent types are ignored
(isinstance check is type narrowing, not a re-entrant guard).
"""

import logging

from tastytrade.analytics.engines.protocol import SignalEngine
from tastytrade.messaging.models.events import BaseEvent, CandleEvent

logger = logging.getLogger(__name__)


class SignalEventProcessor:
    """Routes CandleEvent to a SignalEngine.

    Implements the EventProcessor protocol (name, process_event, close).
    Should be attached to the Candle EventHandler.

    Signal emission is handled externally — wire ``engine.on_signal``
    to a ``RedisPublisher.publish`` (or any callback) before processing.
    """

    name: str = "signal"

    def __init__(self, engine: SignalEngine) -> None:
        self.engine = engine

    def process_event(self, event: BaseEvent) -> None:
        if isinstance(event, CandleEvent):
            self.engine.on_candle_event(event)

    def close(self) -> None:
        logger.info("SignalEventProcessor closing")
