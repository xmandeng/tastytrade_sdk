# ! NEEDS ERROR HANDLING - WHEN INFLUXDB IS DOWN, THE PROCESSOR SHOULD ALERT
import os
from datetime import datetime

from influxdb_client import InfluxDBClient, Point

from tastytrade.messaging.models.events import BaseEvent, CandleEvent
from tastytrade.messaging.processors.default import BaseEventProcessor


class TelegrafHTTPEventProcessor(BaseEventProcessor):
    name = "telegraf_http"

    def __init__(self):
        self.client = InfluxDBClient(
            url="http://influxdb:8086",
            token=os.environ["INFLUX_DB_TOKEN"],
            org=os.environ["INFLUX_DB_ORG"],
        )
        self.write_api = self.client.write_api()

    def process_event(self, event: BaseEvent) -> BaseEvent:
        point = Point(event.__class__.__name__)
        point.tag("eventSymbol", event.eventSymbol)

        if hasattr(event, "tradeDate"):
            assert isinstance(event, CandleEvent)
            point.tag("tradeDate", event.tradeDate)

        if hasattr(event, "tradeDateUTC"):
            assert isinstance(event, CandleEvent)
            point.tag("tradeDateUTC", event.tradeDateUTC)

            if hasattr(event, "tradeTime"):
                assert isinstance(event, CandleEvent)
            point.tag("tradeTime", event.tradeTime)

            if hasattr(event, "tradeTimeUTC"):
                assert isinstance(event, CandleEvent)
                point.tag("tradeTimeUTC", event.tradeTimeUTC)

        if hasattr(event, "prevDate"):
            assert isinstance(event, CandleEvent)
            point.tag("prevDate", event.prevDate)

        if hasattr(event, "prevTime"):
            assert isinstance(event, CandleEvent)
            point.tag("prevTime", event.prevTime)

        for attr, value in event.__dict__.items():
            if attr not in [
                "eventSymbol",
                "time",
                "tradeDate",
                "tradeTime",
                "tradeDateUTC",
                "tradeTimeUTC",
                "prevDate",
                "prevTime",
            ]:
                point.field(attr, value)

        if hasattr(event, "time"):
            assert isinstance(event.time, datetime)
            point.time(event.time)

        self.write_api.write(bucket=os.environ["INFLUX_DB_BUCKET"], record=point)

        return event
