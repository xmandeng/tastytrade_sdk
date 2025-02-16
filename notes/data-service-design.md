# Data Service Architecture

## Overview

This document outlines a flexible architecture for managing time-series data that combines historical data access with live streaming updates. The design uses abstract base classes for core functionality while planning for future caching enhancements.

## Core Architecture

### Base Abstract Class

```python
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict

class DataService(ABC):
    """Base class for time-series data access."""

    def __init__(self):
        self._frames: Dict[str, pl.DataFrame] = {}
        self._updates: Dict[str, datetime] = {}
        self._processors: Dict[str, EventProcessor] = {}

    @abstractmethod
    async def get_history(
        self,
        id: str,
        start: datetime,
        end: Optional[datetime] = None
    ) -> pl.DataFrame:
        """Get historical data."""
        pass

    @abstractmethod
    async def subscribe(self, id: str) -> None:
        """Setup live data streaming."""
        pass

    async def get(
        self,
        id: str,
        start: datetime,
        end: Optional[datetime] = None,
        live: bool = True
    ) -> pl.DataFrame:
        """Get combined historical and live data."""
        df = await self.get_history(id, start, end)

        if live:
            if id not in self._processors:
                await self.subscribe(id)
            if id in self._frames:
                df = pl.concat([df, self._frames[id]])

        return df
```

### Market Data Implementation

```python
class MarketData(DataService):
    """Market data implementation."""

    def __init__(self, influx_client, dxlink_manager):
        super().__init__()
        self.influx = influx_client
        self.dxlink = dxlink_manager

    async def get_history(
        self,
        id: str,
        start: datetime,
        end: Optional[datetime] = None
    ) -> pl.DataFrame:
        query = self._build_query(id, start, end)
        results = await self.influx.query(query)
        return pl.DataFrame(results)

    async def subscribe(self, id: str) -> None:
        processor = LiveDataProcessor(
            symbol=id,
            on_event=lambda evt: self._update(id, evt)
        )
        self._processors[id] = processor
        self.dxlink.router.add_processor(processor)

    def _update(self, id: str, event: Any) -> None:
        """Handle live updates."""
        if id not in self._frames:
            self._frames[id] = pl.DataFrame()

        self._frames[id] = self._frames[id].vstack(
            pl.DataFrame([event])
        )
        self._updates[id] = datetime.now()
```

## Usage Example

```python
# Initialize service
market = MarketData(influx_client, dxlink_manager)

# Get data with live updates
data = await market.get(
    id="SPY",
    start=datetime.now() - timedelta(days=30),
    live=True
)

# Compute study
study = compute_moving_average(data, period=20)
```

## Future Enhancement: Caching Layer

When user demand increases, implement caching:

```python
class CachedDataService(DataService):
    """Future implementation with query caching."""

    def __init__(self):
        super().__init__()
        self._query_cache: Dict[str, Tuple[pl.DataFrame, datetime]] = {}
        self._cache_ttl = timedelta(minutes=5)

    async def get(self, id: str, start: datetime, end: Optional[datetime] = None) -> pl.DataFrame:
        cache_key = self._make_key(id, start, end)

        # Check cache
        if cache_key in self._query_cache:
            df, timestamp = self._query_cache[cache_key]
            if datetime.now() - timestamp < self._cache_ttl:
                return df

        # Get fresh data
        df = await super().get(id, start, end)

        # Cache result
        self._query_cache[cache_key] = (df, datetime.now())
        return df
```

### Cache Implementation Details

When needed, the caching layer will provide:

1. **Query Result Caching**
   - Store processed data for frequent queries
   - LRU eviction policy
   - Configurable TTL
   - Memory usage monitoring

2. **Memory Management**
   - Automatic cache cleanup
   - Size-based eviction
   - Time-based invalidation
   - Resource monitoring

## Benefits

1. **Clean Architecture**
   - Clear separation of concerns
   - Easy to implement new data sources
   - Consistent interface
   - Type-safe through ABCs

2. **Efficient Data Access**
   - Combined historical and live data
   - Single interface for all data needs
   - Ready for caching when needed

3. **Maintainable**
   - Concise method names
   - Clear responsibilities
   - Easy to extend
   - Well-defined interfaces

## Implementation Path

1. Start with base `DataService` and `MarketData` implementation
2. Add monitoring and logging
3. Implement caching when user demand increases
4. Add additional data source implementations as needed
