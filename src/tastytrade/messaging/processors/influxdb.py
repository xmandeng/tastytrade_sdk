# ! NEEDS ERROR HANDLING - WHEN INFLUXDB IS DOWN, THE PROCESSOR SHOULD ALERT
import logging
import os
from datetime import datetime

from influxdb_client import InfluxDBClient, Point

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor

logger = logging.getLogger(__name__)


class TelegrafHTTPEventProcessor(BaseEventProcessor):
    name = "telegraf_http"

    def __init__(self):
        self.client = InfluxDBClient(
            url="http://influxdb:8086",
            token=os.environ["INFLUX_DB_TOKEN"],
            org=os.environ["INFLUX_DB_ORG"],
        )
        self.write_api = self.client.write_api()

    def process_event(self, event: BaseEvent) -> None:
        point = Point(event.__class__.__name__)
        point.tag("eventSymbol", event.eventSymbol)

        if hasattr(event, "time"):
            assert isinstance(event.time, datetime)
            point.time(event.time)

        for attr, value in event.__dict__.items():
            if attr not in [
                "eventSymbol",
                "time",
            ]:
                if value is None:
                    continue
                if isinstance(value, datetime):
                    point.field(attr, value.isoformat())
                else:
                    point.field(attr, value)

        self.write_api.write(bucket=os.environ["INFLUX_DB_BUCKET"], record=point)

    def close(self) -> None:
        """Flush pending writes and close the InfluxDB client."""
        logger.info("Flushing InfluxDB write API...")
        self.write_api.close()
        self.client.close()
        logger.info("InfluxDB client closed")
