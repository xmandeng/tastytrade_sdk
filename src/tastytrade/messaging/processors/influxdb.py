# ! NEEDS ERROR HANDLING - WHEN INFLUXDB IS DOWN, THE PROCESSOR SHOULD ALERT
import logging
import os
import threading
from datetime import datetime

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
FLUSH_INTERVAL_SECONDS = 1.0


class TelegrafHTTPEventProcessor(BaseEventProcessor):
    name = "telegraf_http"

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        org: str | None = None,
        bucket: str | None = None,
        batch_size: int = BATCH_SIZE,
        flush_interval_seconds: float = FLUSH_INTERVAL_SECONDS,
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
        # TT-157: hand-rolled batching on one writer thread. TT-108 replaced
        # reactivex batching (broken on Python 3.13) with per-event
        # WriteType.asynchronous writes; under market-hours candle volume the
        # one-HTTP-call-per-event thread-pool traffic starved the event loop
        # and live consumers fell hours behind the tape. Points buffer here
        # and flush every flush_interval_seconds or batch_size points,
        # whichever comes first — a single synchronous batch write per flush,
        # off the event loop, no reactivex.
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.bucket = bucket
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self.pending: list[Point] = []
        self.pending_lock = threading.Lock()
        self.wake = threading.Event()
        self.closing = False
        self.flusher = threading.Thread(
            target=self.flush_loop, name="influx-flusher", daemon=True
        )
        self.flusher.start()

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

        with self.pending_lock:
            self.pending.append(point)
            full = len(self.pending) >= self.batch_size
        if full:
            self.wake.set()

    def flush_loop(self) -> None:
        while not self.closing:
            self.wake.wait(timeout=self.flush_interval_seconds)
            self.wake.clear()
            self.flush_pending()
        self.flush_pending()

    def flush_pending(self) -> None:
        with self.pending_lock:
            if not self.pending:
                return
            batch, self.pending = self.pending, []
        try:
            self.write_api.write(bucket=self.bucket, record=batch)
        except Exception:
            # Loud, not silent: these points are lost. A retry queue is a
            # deliberate non-goal here — better to surface an unhealthy
            # InfluxDB than to grow an unbounded retry backlog (TT-157).
            logger.exception(
                "InfluxDB batch write failed — %d points dropped", len(batch)
            )

    def close(self) -> None:
        """Flush pending writes and close the InfluxDB client."""
        logger.info("Flushing InfluxDB write API...")
        self.closing = True
        self.wake.set()
        self.flusher.join(timeout=10)
        self.flush_pending()
        self.write_api.close()
        self.client.close()
        logger.info("InfluxDB client closed")
