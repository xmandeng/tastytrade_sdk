# ! NEEDS ERROR HANDLING - WHEN INFLUXDB IS DOWN, THE PROCESSOR SHOULD ALERT
import os
from datetime import datetime

from influxdb_client import InfluxDBClient, Point

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor


class TelegrafHTTPEventProcessor(BaseEventProcessor):
    name = "telegraf_http"

    def __init__(self):
        self.client = InfluxDBClient(
            url=os.environ["INFLUX_DB_URL"],
            token=os.environ["INFLUX_DB_TOKEN"],
            org=os.environ["INFLUX_DB_ORG"],
        )
        self.write_api = self.client.write_api()

    def process_event(self, event: BaseEvent) -> None:
        point = Point(event.__class__.__name__)
        point.tag("eventSymbol", event.eventSymbol)

        for attr, value in event.__dict__.items():
            if attr not in ["eventSymbol", "time"]:
                point.field(attr, value)

        if hasattr(event, "time"):
            assert isinstance(event.time, datetime)
            point.time(event.time)

        self.write_api.write(bucket=os.environ["INFLUX_DB_BUCKET"], record=point)
