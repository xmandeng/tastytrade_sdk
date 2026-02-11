"""Market data provider implementation."""

import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Callable, Optional, Union, overload

if TYPE_CHECKING:
    from tastytrade.messaging.models.events import CandleEvent

import polars as pl
from influxdb_client import InfluxDBClient

from tastytrade.config import RedisConfigManager
from tastytrade.messaging.models.events import BaseEvent
from tastytrade.providers.subscriptions import DataSubscription

logger = logging.getLogger(__name__)

config = RedisConfigManager()


class MarketDataProvider:
    """Provider for market data combining historical and live sources."""

    event_type: str = "CandleEvent"

    def __init__(
        self,
        data_feed: DataSubscription,
        influx: InfluxDBClient,
        event_type: Optional[str] = None,
    ) -> None:
        """Initialize the market data provider."""
        self.influx = influx
        self.data_feed = data_feed
        self.event_type = event_type or self.event_type

        self.frames: dict[str, pl.DataFrame] = {}
        self.updates: dict[str, datetime] = {}
        self.handlers: dict[str, Callable] = {}

        logger.debug("Initialized DataProviderService")

    def __getitem__(self, item: str) -> pl.DataFrame:
        """Implements behavior for accessing func[item]"""
        if item in self.frames:
            return self.frames[item]
        else:
            self.frames[item] = pl.DataFrame()
            return self.frames[item]

    def __setitem__(self, item: str, df: pl.DataFrame) -> None:
        """Implements behavior for assigning func[item] = value"""
        self.frames[item] = df

    def __contains__(self, item: str) -> bool:
        """Implements behavior for 'item in func'"""
        return item in self.frames

    def __len__(self) -> int:
        """Implements behavior for len(func)"""
        return len(self.frames)

    def __iter__(self):
        """Implements behavior for iteration"""
        return iter(self.frames)

    @overload
    def download(
        self,
        symbol: str,
        start: datetime,
        stop: Optional[datetime] = None,
        debug_mode: bool = False,
    ) -> pl.DataFrame: ...

    @overload
    def download(
        self,
        symbol: str,
        start: date,
        stop: Optional[date] = None,
        debug_mode: bool = False,
    ) -> pl.DataFrame: ...

    def download(
        self,
        symbol: str,
        start: Union[datetime, date],
        stop: Optional[Union[datetime, date]] = None,
        debug_mode: bool = False,
    ) -> pl.DataFrame:
        """Get historical market data from InfluxDB.

        Uses Flux pivot operation to transform field-based records into rows that
        match our event model structure.

        Args:
            symbol: Market symbol to query
            start: Start time for historical data
            end: Optional end time
            event_type: Type of event to retrieve (e.g. TradeEvent, QuoteEvent)
        """

        # Normalize date inputs to naive UTC-midnight datetimes (consistent with existing behavior)
        def coerce(dt: Union[datetime, date]) -> datetime:
            if isinstance(dt, datetime):
                return dt
            return datetime(dt.year, dt.month, dt.day)

        start_dt = coerce(start)
        stop_dt = coerce(stop) if stop else None

        if stop_dt and stop_dt <= start_dt:
            raise ValueError("Stop time must be greater than start time")

        if stop_dt:
            date_range = f"{start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}, stop: {stop_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})"
        else:
            date_range = f"{start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')})"

        pivot_query = f"""
            from(bucket: "{config.get("INFLUX_DB_BUCKET") or os.environ["INFLUX_DB_BUCKET"]}")
            |> range(start: {date_range}
            |> filter(fn: (r) => r["_measurement"] == "{self.event_type}")
            |> filter(fn: (r) => r["eventSymbol"] == "{symbol}")
            |> pivot(
                rowKey: ["_time"],
                columnKey: ["_field"],
                valueColumn: "_value"
                )
            """

        logger.debug("Subscription query:\n%s", pivot_query)

        try:
            # Query returns a pandas DataFrame (or list). Normalize to DataFrame.
            raw = self.influx.query_api().query_data_frame(pivot_query)
            import pandas as _pd  # local import to keep top-level light

            if isinstance(raw, list):
                raw = _pd.concat(raw, ignore_index=True) if raw else _pd.DataFrame()
            df = raw.assign(time=lambda d: d["_time"].dt.tz_localize(None))

            # Remove InfluxDB metadata columns
            df = df.drop(
                columns=[
                    col
                    for col in [
                        "result",
                        "table",
                        "_start",
                        "_stop",
                        "_time",
                        "_measurement",
                    ]
                    if col in df
                ]
            )

        except Exception as e:
            logger.error(
                "Error querying InfluxDB for %s (%s): %s", symbol, self.event_type, e
            )
            raise ValueError(
                f"Error querying InfluxDB for {symbol} ({self.event_type}): {e}"
            ) from e

        result = pl.from_pandas(df)
        if debug_mode:
            return result
        self.frames[symbol] = result
        return result

    def get_daily_candle(self, symbol: str, target_date: date) -> "CandleEvent":
        """Fetch a single daily candle for a symbol and date.

        Rewrites any interval suffix to daily ({=d}), downloads one day of
        data from InfluxDB, and returns a CandleEvent.

        Args:
            symbol: Market symbol in any format (e.g. "SPX", "SPX{=m}", "SPX{=5m}").
            target_date: The date to fetch the daily candle for.

        Returns:
            A CandleEvent with OHLCV fields populated.

        Raises:
            ValueError: If no candle data is found for the given symbol and date.
        """
        from tastytrade.messaging.models.events import CandleEvent

        daily_symbol = re.sub(r"\{=.*?\}", "", symbol) + "{=d}"

        df = self.download(
            symbol=daily_symbol,
            start=target_date,
            stop=target_date + timedelta(days=1),
            debug_mode=True,
        )

        if df.is_empty():
            raise ValueError(
                f"No daily candle found for {daily_symbol} on {target_date}"
            )

        return CandleEvent(**df.to_dicts().pop())

    def event_listener(self):
        pass

    def handle_update(self, event: BaseEvent) -> None:
        """Handle incoming market data events."""
        event_key = f"{event.__class__.__name__}:{event.eventSymbol}"

        try:
            self.frames[event_key] = (
                pl.concat(
                    [self.frames.get(event_key, pl.DataFrame()), pl.DataFrame([event])],
                    how="diagonal",
                )
                .unique(subset=["eventSymbol", "time"], keep="last")
                .sort("time", descending=False)
            )

            self.updates[event_key] = datetime.now()

        except Exception as e:
            logger.error(
                "Error handling update for %s: %s",
                event_key,
                e,
            )

    async def subscribe(
        self, event_type: str, symbol: str, subscription_prefix: str = "market:"
    ) -> None:
        """Setup live market data streaming via DataSubscription."""
        try:
            await self.data_feed.subscribe(
                channel_pattern=f"{subscription_prefix}:{event_type}:{symbol}",
                on_update=self.handle_update,
            )
            self.event_listener()
            logger.info("Subscribed to %s", symbol)

        except Exception as e:
            logger.error("Error setting up subscription for %s: %s", symbol, e)

    async def unsubscribe(self, event_type: str, symbol: str) -> None:
        """Stop live data streaming for the given symbol."""
        await self.data_feed.unsubscribe(
            channel_pattern=f"market:{event_type}:{symbol}"
        )


# Extend MarketDataProvider with callback support
class EventDrivenProvider(MarketDataProvider):
    """Extension of MarketDataProvider with event callback support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_callbacks = {}

    def register_update_callback(self, event_symbol: str, callback):
        """Register a callback to be triggered when data for a symbol is updated."""
        if event_symbol not in self.update_callbacks:
            self.update_callbacks[event_symbol] = []
        self.update_callbacks[event_symbol].append(callback)
        logger.debug(f"Registered update callback for {event_symbol}")
        return callback  # Return the callback for convenience

    def unregister_update_callback(self, event_symbol: str, callback):
        """Remove a registered callback."""
        if (
            event_symbol in self.update_callbacks
            and callback in self.update_callbacks[event_symbol]
        ):
            self.update_callbacks[event_symbol].remove(callback)
            logger.debug(f"Unregistered update callback for {event_symbol}")

    def handle_update(self, event: BaseEvent) -> None:
        """Handle incoming market data events and trigger callbacks."""
        event_key = f"{event.__class__.__name__}:{event.eventSymbol}"

        # Call the original handle_update method
        super().handle_update(event)

        # Trigger callbacks if registered for this symbol
        if event_key in self.update_callbacks and self.update_callbacks[event_key]:
            for callback in self.update_callbacks[event_key]:
                try:
                    callback(event_key, event)
                except Exception as e:
                    logger.error(f"Error in update callback for {event_key}: {e}")
