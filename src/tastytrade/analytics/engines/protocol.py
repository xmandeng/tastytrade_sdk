"""Protocol definition for signal detection engines.

Uses typing.Protocol for structural subtyping — any class that implements
these methods is a valid SignalEngine without explicit inheritance.
"""

from typing import Callable, Protocol

from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.messaging.models.events import CandleEvent


class SignalEngine(Protocol):
    """Structural protocol for signal detection engines."""

    @property
    def name(self) -> str: ...

    @property
    def signals(self) -> list[TradeSignal]: ...

    @property
    def on_signal(self) -> Callable[[TradeSignal], None] | None: ...

    @on_signal.setter
    def on_signal(self, callback: Callable[[TradeSignal], None] | None) -> None: ...

    def set_prior_close(self, event_symbol: str, price: float) -> None: ...

    def on_candle_event(self, event: CandleEvent) -> None: ...
