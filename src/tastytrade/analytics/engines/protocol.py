"""Protocol definition for signal detection engines.

Uses typing.Protocol for structural subtyping — any class that implements
these methods is a valid SignalEngine without explicit inheritance.
"""

from typing import Protocol

from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.messaging.models.events import CandleEvent
from tastytrade.messaging.publisher import EventPublisher


class SignalEngine(Protocol):
    """Structural protocol for signal detection engines."""

    @property
    def name(self) -> str: ...

    @property
    def signals(self) -> list[TradeSignal]: ...

    @property
    def publisher(self) -> EventPublisher | None: ...

    @publisher.setter
    def publisher(self, value: EventPublisher | None) -> None: ...

    def set_prior_close(self, event_symbol: str, price: float) -> None: ...

    def on_candle_event(self, event: CandleEvent) -> None: ...
