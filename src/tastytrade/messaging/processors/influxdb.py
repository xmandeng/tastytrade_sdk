# ! NEEDS ERROR HANDLING - WHEN INFLUXDB IS DOWN, THE PROCESSOR SHOULD ALERT
import logging
import os
from datetime import datetime

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import WriteOptions, WriteType

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor

logger = logging.getLogger(__name__)


class TelegrafHTTPEventProcessor(BaseEventProcessor):
    name = "telegraf_http"

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        org: str | None = None,
        bucket: str | None = None,
    ):
        # Service discovery: explicit param → os.environ → raise
        # See docs/SERVICE_DISCOVERY.md
        url = url or os.environ.get("INFLUX_DB_URL", "http://localhost:8086")
        token = token or os.environ.get("INFLUX_DB_TOKEN")
        org = org or os.environ.get("INFLUX_DB_ORG")
        bucket = bucket or os.environ.get("INFLUX_DB_BUCKET")
        if not token:
            raise ValueError(
                "INFLUX_DB_TOKEN is required. Set via parameter or INFLUX_DB_TOKEN env var."
            )
        if not org:
            raise ValueError(
                "INFLUX_DB_ORG is required. Set via parameter or INFLUX_DB_ORG env var."
            )
        if not bucket:
            raise ValueError(
                "INFLUX_DB_BUCKET is required. Set via parameter or INFLUX_DB_BUCKET env var."
            )

        self.client = InfluxDBClient(url=url, token=token, org=org)
        # Use asynchronous (non-batching) writes to avoid reactivex operators
        # that are broken on Python 3.13. Each write dispatches to a thread
        # pool immediately — no event loop blocking, no reactivex dependency.
        self.write_api = self.client.write_api(
            write_options=WriteOptions(write_type=WriteType.asynchronous)
        )
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
