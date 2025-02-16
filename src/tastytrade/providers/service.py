"""Base abstractions for data provider services."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

import polars as pl

from tastytrade.messaging.processors.default import EventProcessor

logger = logging.getLogger(__name__)


class DataProcessor(Protocol):
    """Protocol defining the interface for data processing components."""

    name: str

    def process_event(self, event: Any) -> Any: ...


class DataProviderService(ABC):
    """Abstract base class for data provider services.

    This class defines the core interface for accessing time-series data,
    supporting both historical data retrieval and live streaming updates.

    Attributes
        frames: Dictionary mapping symbols to their live data frames
        updates: Dictionary tracking last update times per symbol
        processors: Dictionary of active data processors per symbol
    """

    def __init__(self) -> None:
        """Initialize data provider service state."""
        self.frames: Dict[str, pl.DataFrame] = {}
        self.updates: Dict[str, datetime] = {}
        self.processors: Dict[str, EventProcessor] = {}
        logger.debug("Initialized DataProviderService")

    @abstractmethod
    async def get_history(
        self, symbol: str, start: datetime, end: Optional[datetime] = None
    ) -> pl.DataFrame:
        """Get historical data for the given symbol and time range."""
        pass

    @abstractmethod
    async def subscribe(self, symbol: str) -> None:
        """Setup live data streaming for the given symbol."""
        pass

    async def unsubscribe(self, symbol: str) -> None:
        """Stop live data streaming for the given symbol."""
        if symbol in self.processors:
            logger.info("Unsubscribing from %s", symbol)
            # Just pop without assignment since we don't use the processor
            self.processors.pop(symbol)
            if symbol in self.frames:
                del self.frames[symbol]
            if symbol in self.updates:
                del self.updates[symbol]
            logger.debug("Cleaned up resources for %s", symbol)

    async def get(
        self, symbol: str, start: datetime, end: Optional[datetime] = None, live: bool = True
    ) -> pl.DataFrame:
        """Get combined historical and live data."""
        logger.debug(
            "Getting data for %s from %s to %s (live=%s)", symbol, start, end or "now", live
        )

        df = await self.get_history(symbol, start, end)
        logger.debug("Retrieved %d historical records", len(df))

        if live:
            if symbol not in self.processors:
                logger.debug("Setting up live subscription for %s", symbol)
                await self.subscribe(symbol)
            if symbol in self.frames:
                logger.debug("Combining with %d live records", len(self.frames[symbol]))
                df = pl.concat([df, self.frames[symbol]], how="vertical")

        # Deduplicate by timestamp keeping most recent
        result = df.unique(subset=["time"], keep="last")
        logger.debug("Returning %d total records after deduplication", len(result))
        return result
