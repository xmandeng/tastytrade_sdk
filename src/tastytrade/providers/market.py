"""Market data provider implementation."""

import logging
from datetime import datetime
from typing import Optional

import polars as pl
from influxdb_client import InfluxDBClient

from tastytrade.config.configurations import CHANNEL_SPECS, ChannelSpecification
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.messaging.models.events import BaseEvent
from tastytrade.providers.processors.base import BaseEventProcessor  # type: ignore
from tastytrade.providers.processors.live import LiveDataProcessor  # type: ignore
from tastytrade.providers.service import DataProviderService

logger = logging.getLogger(__name__)


class MarketDataProvider(DataProviderService):
    """Provider for market data combining historical and live sources."""

    def __init__(self, influx: InfluxDBClient, dxlink: DXLinkManager) -> None:
        """Initialize the market data provider."""
        super().__init__()
        self.influx = influx
        self.dxlink = dxlink

    def get_channel_spec(self, event_type: str) -> Optional[ChannelSpecification]:
        """Get channel specification for event type."""
        for channel, spec in CHANNEL_SPECS.items():
            if spec.type == event_type:
                return spec
        return None

    async def get_history(
        self,
        symbol: str,
        start: datetime,
        end: Optional[datetime] = None,
        event_type: str = "CandleEvent",
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
        spec = self.get_channel_spec(event_type)
        if not spec:
            logger.error("Unsupported event type: %s", event_type)
            return pl.DataFrame()

        try:
            # Get fields from channel specification
            value_fields = spec.fields
            value_fields_str = '", "'.join(value_fields)

            # Get tags (metadata fields) from the model
            model = spec.event_type.value
            tag_fields = [
                field_name
                for field_name, field in model.model_fields.items()
                if (
                    isinstance(field.annotation, str)
                    and field.annotation != "datetime"
                    and field_name not in value_fields
                )
            ]

            query = f"""
            from(bucket: "tastytrade")
                |> range(start: {start.isoformat()}, stop: {end.isoformat() if end else "now()"})
                |> filter(fn: (r) => r._measurement == "{event_type}")
                |> filter(fn: (r) => r.eventSymbol == "{symbol}")
                |> filter(fn: (r) => contains(value: r._field, set: ["{value_fields_str}"]))
                |> pivot(
                    rowKey: ["_time", "eventSymbol"{', "' + '", "'.join(tag_fields) + '"' if tag_fields else ''}],
                    columnKey: ["_field"],
                    valueColumn: "_value"
                )
            """

            tables = self.influx.query_api().query(query, org=self.influx.org)

            if not tables:
                logger.info("No data found for %s (%s)", symbol, event_type)
                return pl.DataFrame()

            # Convert to list of dicts with proper timestamp handling
            records = []
            for table in tables:
                for record in table.records:
                    # Start with any tag fields
                    record_dict = {
                        "eventSymbol": symbol,
                        # Map _time to time
                        "time": record.get_time(),
                    }

                    # Add tag fields
                    for tag in tag_fields:
                        if tag in record.values:
                            record_dict[tag] = record.values[tag]

                    # Add value fields, excluding internal InfluxDB fields
                    for key, value in record.values.items():
                        if (
                            not key.startswith("_")
                            and key not in ["result", "table"]
                            and key in value_fields
                        ):
                            record_dict[key] = value

                    try:
                        # Validate record against event model
                        model(**record_dict)  # Validate but don't keep
                        records.append(record_dict)
                    except Exception as e:
                        logger.warning(
                            "Invalid record for %s: %s Record: %s", event_type, e, record_dict
                        )
                        continue

            if not records:
                logger.warning("No valid records found after processing")
                return pl.DataFrame()

            logger.info("Retrieved %d historical %s records", len(records), event_type)
            return pl.DataFrame(records)

        except Exception as e:
            logger.error("Error querying InfluxDB for %s (%s): %s", symbol, event_type, e)
            return pl.DataFrame()

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
            self.dxlink.router.add_processor(processor)
            await self.dxlink.subscribe([symbol])
            logger.info("Subscribed to %s", symbol)

        except Exception as e:
            logger.error("Error setting up subscription for %s: %s", symbol, e)

    def handle_update(self, symbol: str, event: BaseEvent) -> None:
        """Handle incoming live market data updates."""
        try:
            if symbol not in self.frames:
                self.frames[symbol] = pl.DataFrame()

            # Use BaseEventProcessor for consistent structure
            processor = BaseEventProcessor()
            processor.process_event(event)

            self.frames[symbol] = pl.concat([self.frames[symbol], processor.pl], how="vertical")

            self.updates[symbol] = datetime.now()

        except Exception as e:
            logger.error("Error handling update for %s: %s", symbol, e)
