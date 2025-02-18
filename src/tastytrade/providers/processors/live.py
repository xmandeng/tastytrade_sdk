"""Live data processor implementation."""

import logging
from typing import Callable

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.providers.processors.base import BaseEventProcessor

logger = logging.getLogger(__name__)


class LiveDataProcessor(BaseEventProcessor):
    """Processor for live streaming data."""

    def __init__(self, symbol: str, on_update: Callable[[BaseEvent], None]) -> None:
        """Initialize the live data processor.

        Args:
            symbol: Symbol to process data for
            on_update: Callback function for handling updates
        """
        super().__init__()
        self.name = f"live_{symbol}"
        self.symbol = symbol
        self.on_update = on_update

    def process_event(self, event: BaseEvent) -> None:
        """Process a live event.

        Processes the event and triggers the update callback.

        Args:
            event: Event to process
        """
        super().process_event(event)
        self.on_update(event)
