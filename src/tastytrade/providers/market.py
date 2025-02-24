"""Market data provider implementation."""

import logging
import os
from datetime import datetime
from typing import Optional

import polars as pl
from influxdb_client import InfluxDBClient

from tastytrade.config.enumerations import Channels
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor
from tastytrade.providers.processors.live import LiveDataProcessor

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Provider for market data combining historical and live sources."""

    event_type: str = "CandleEvent"

    def __init__(
        self, dxlink: DXLinkManager, influx: InfluxDBClient, event_type: Optional[str] = None
    ) -> None:
        """Initialize the market data provider."""
        self.influx = influx
        self.dxlink = dxlink
        self.event_type = event_type or self.event_type

        self.frames: dict[str, pl.DataFrame] = {}
        self.updates: dict[str, datetime] = {}
        self.processors: dict[str, BaseEventProcessor] = {}

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

    def download(
        self,
        symbol: str,
        start: datetime = datetime.now(),
        stop: Optional[datetime] = None,
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
        if stop:
            date_range = f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}, stop: {stop.strftime('%Y-%m-%dT%H:%M:%SZ')})"
        else:
            date_range = f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')})"

        pivot_query = f"""
            from(bucket: "{os.environ["INFLUX_DB_BUCKET"]}")
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
            df = (
                self.influx.query_api().query_data_frame(pivot_query)
                # Add CandleEvent time w/o timezone
                .assign(time=lambda df: df["_time"].dt.tz_localize(None))
            )

            # Remove InfluxDB metadata columns
            df = df.drop(
                columns=[
                    col
                    for col in ["result", "table", "_start", "_stop", "_time", "_measurement"]
                    if col in df
                ]
            )

        except Exception as e:
            logger.error("Error querying InfluxDB for %s (%s): %s", symbol, self.event_type, e)
            raise ValueError(f"Error querying InfluxDB for {symbol} ({self.event_type}): {e}")

        if debug_mode:
            return pl.from_pandas(df)
        else:
            self.frames[symbol] = pl.from_pandas(df)

    def handle_update(self, symbol: str, event: BaseEvent) -> None:
        """Handle incoming live market data updates."""
        if event.eventSymbol != symbol:
            return

        new_event = pl.DataFrame([event])

        try:
            self.frames[symbol] = (
                pl.concat([self.frames[symbol], new_event], how="diagonal")
                .unique(subset=["eventSymbol", "time"], keep="last")
                .sort("time", descending=False)
            )

            self.updates[symbol] = datetime.now()

        except Exception as e:
            logger.error("Error handling update for %s: %s", symbol, e)

    async def subscribe(self, symbol: str) -> None:
        """Setup live market data streaming via DXLink."""
        if not self.dxlink.router:
            logger.error("DXLink router not initialized")
            return

        try:
            processor = LiveDataProcessor(
                symbol=symbol, on_update=lambda event: self.handle_update(symbol, event)
            )

            self.processors[symbol] = processor
            self.dxlink.router.handler[Channels.Candle].add_processor(processor)

            subscriptions = await self.dxlink.get_active_subscriptions()
            if symbol not in subscriptions:
                await self.dxlink.subscribe([symbol])

            logger.info("Subscribed to %s", symbol)

        except Exception as e:
            logger.error("Error setting up subscription for %s: %s", symbol, e)

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


async def main() -> pl.DataFrame:
    from dotenv import load_dotenv

    load_dotenv("/workspace/.env")

    from influxdb_client import InfluxDBClient

    from tastytrade.connections import Credentials, InfluxCredentials
    from tastytrade.connections.sockets import DXLinkManager

    credentials = Credentials(env="Live")

    influx_user = InfluxCredentials()
    influx = InfluxDBClient(
        url=InfluxCredentials().url, token=influx_user.token, org=influx_user.org
    )
    async with DXLinkManager(credentials=credentials) as dxlink:

        market = MarketDataProvider(dxlink, influx)
        df = market.download(
            "SPX{=5m}", start=datetime(2025, 2, 20), stop=datetime(2025, 2, 21), debug_mode=True
        )

        return df


if __name__ == "__main__":
    import asyncio

    df = asyncio.run(main())
    print(df)
