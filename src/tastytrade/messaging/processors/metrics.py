"""Event processor that routes QuoteEvent and GreeksEvent to MetricsTracker.

Attach to the Quote and Greeks EventHandlers. Other event types are ignored.
"""

import logging

from tastytrade.analytics.metrics import MetricsTracker
from tastytrade.messaging.models.events import BaseEvent, GreeksEvent, QuoteEvent

logger = logging.getLogger(__name__)


class MetricsEventProcessor:
    """Routes QuoteEvent and GreeksEvent to a shared MetricsTracker.

    Implements the EventProcessor protocol (name, process_event, close).
    Should be attached to both the Quote and Greeks handlers.
    """

    name: str = "metrics"

    def __init__(self, tracker: MetricsTracker) -> None:
        self.tracker = tracker

    def process_event(self, event: BaseEvent) -> None:
        """Route QuoteEvent and GreeksEvent to the MetricsTracker."""
        if isinstance(event, QuoteEvent):
            self.tracker.on_quote_event(event)
        elif isinstance(event, GreeksEvent):
            self.tracker.on_greeks_event(event)

    def close(self) -> None:
        """No-op close. MetricsTracker lifecycle is managed externally."""
        pass
