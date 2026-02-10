"""Event processor that routes QuoteEvent to MetricsTracker.

Attach to the Quote EventHandler only. Other event types are ignored.
"""

import logging

from tastytrade.analytics.metrics import MetricsTracker
from tastytrade.messaging.models.events import BaseEvent, QuoteEvent

logger = logging.getLogger(__name__)


class MetricsEventProcessor:
    """Routes QuoteEvent to a shared MetricsTracker.

    Implements the EventProcessor protocol (name, process_event, close).
    Unlike Redis/Telegraf processors that attach to ALL handlers, this
    processor should be attached ONLY to the Quote handler.
    """

    name: str = "metrics"

    def __init__(self, tracker: MetricsTracker) -> None:
        self.tracker = tracker

    def process_event(self, event: BaseEvent) -> None:
        """Route QuoteEvent to the MetricsTracker. All other types ignored."""
        if isinstance(event, QuoteEvent):
            self.tracker.on_quote_event(event)

    def close(self) -> None:
        """No-op close. MetricsTracker lifecycle is managed externally."""
        pass
