# ! NEEDS ERROR HANDLING - WHEN INFLUXDB IS DOWN, THE PROCESSOR SHOULD ALERT
import logging
from datetime import datetime

from influxdb_client import InfluxDBClient, Point

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor

logger = logging.getLogger(__name__)


class TelegrafHTTPEventProcessor(BaseEventProcessor):
    name = "telegraf_http"

    def __init__(
        self,
        url: str = "http://influxdb:8086",
        token: str | None = None,
        org: str | None = None,
        bucket: str | None = None,
    ):
        if not token:
            raise ValueError(
                "INFLUX_DB_TOKEN is required. Ensure it is set in Redis configuration."
            )
        if not org:
            raise ValueError(
                "INFLUX_DB_ORG is required. Ensure it is set in Redis configuration."
            )
        if not bucket:
            raise ValueError(
                "INFLUX_DB_BUCKET is required. Ensure it is set in Redis configuration."
            )

        self.client = InfluxDBClient(url=url, token=token, org=org)
        self.write_api = self.client.write_api()
        self.bucket = bucket

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
                point.field(attr, value)

        self.write_api.write(bucket=self.bucket, record=point)

    def close(self) -> None:
        """Flush pending writes and close the InfluxDB client."""
        logger.info("Flushing InfluxDB write API...")
        self.write_api.close()
        self.client.close()
        logger.info("InfluxDB client closed")
