"""Base event processor implementation."""

import logging

import polars as pl

from tastytrade.messaging.models.events import BaseEvent

logger = logging.getLogger(__name__)


class BaseEventProcessor:
    """Base processor that handles DataFrame storage."""

    name = "feed"

    def __init__(self) -> None:
        self.pl = pl.DataFrame()

    def process_event(self, event: BaseEvent) -> None:
        """Process a single event into the DataFrame.

        Args:
            event: Event to process
        """
        self.pl = self.pl.vstack(pl.DataFrame([event.model_dump()]))

    @property
    def df(self) -> pl.DataFrame:
        """Return current DataFrame."""
        return self.pl
