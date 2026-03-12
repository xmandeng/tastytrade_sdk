"""OTLP metrics export for Redis state observability in Grafana Cloud.

Architecture:
- Observable gauges use sync Redis callbacks (non-blocking, separate connection)
- MeterProvider with PeriodicExportingMetricReader pushes to Grafana Cloud
- Reuses same OTLP gateway as logs, targeting /v1/metrics endpoint

Metrics exported:
- tastytrade.connection.status — gauge per service (1=connected, 0=disconnected, -1=error)
- tastytrade.positions.count — gauge of open positions
- tastytrade.subscriptions.count — gauge of active subscriptions
- tastytrade.orders.count — gauge of tracked orders
- tastytrade.data.freshness_seconds — gauge of data age per subscription type
- tastytrade.reconnections.total — counter of reconnection events

Usage:
    from tastytrade.common.metrics import init_metrics
    init_metrics()
"""

import base64
import json
import logging
import os
import time
from typing import Optional, Sequence

import redis

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import (
    CallbackOptions,
    Counter,
    Observation,
    set_meter_provider,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

# Module-level state
_meter_provider: Optional[MeterProvider] = None
_redis_client: Optional[redis.Redis] = None  # type: ignore[type-arg]
_reconnection_counter: Optional[Counter] = None

# Redis keys (mirrors AccountStreamPublisher and orchestrator constants)
CONNECTION_KEY = "tastytrade:connection"
ACCOUNT_CONNECTION_KEY = "tastytrade:account_connection"
POSITIONS_KEY = "tastytrade:positions"
ORDERS_KEY = "tastytrade:orders"
SUBSCRIPTIONS_KEY = "subscriptions"

# Connection state mapping for numeric gauge values
STATE_VALUES = {"connected": 1, "disconnected": 0, "error": -1}


def init_metrics(
    redis_url: Optional[str] = None,
    export_interval_millis: int = 15000,
) -> Optional[MeterProvider]:
    """Initialize OTLP metrics export pipeline.

    Sets up observable gauges that read Redis state via callbacks,
    and a PeriodicExportingMetricReader that pushes to Grafana Cloud.

    Args:
        redis_url: Redis connection URL. Defaults to redis://localhost:6379.
        export_interval_millis: How often to collect and export metrics.

    Returns:
        The MeterProvider if initialized, None if credentials are missing.
    """
    global _meter_provider, _redis_client, _reconnection_counter

    if _meter_provider is not None:
        return _meter_provider

    # Build OTLP auth header for Grafana Cloud metrics
    instance_id = os.getenv("GRAFANA_CLOUD_METRICS_INSTANCE_ID", "")
    token = os.getenv("GRAFANA_CLOUD_METRICS_TOKEN", "")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    if not (instance_id and token and endpoint):
        logger.info(
            "Metrics export disabled — missing Grafana Cloud metrics credentials"
        )
        return None

    auth_string = f"{instance_id}:{token}"
    auth_b64 = base64.b64encode(auth_string.encode()).decode()
    headers = {"Authorization": f"Basic {auth_b64}"}

    # Create OTLP metric exporter targeting /v1/metrics
    exporter = OTLPMetricExporter(
        endpoint=f"{endpoint}/v1/metrics",
        headers=headers,
        timeout=5,
    )

    # Build resource (shared identity with logs)
    service_name = os.getenv("OTEL_SERVICE_NAME", "tastytrade")
    app_env = os.getenv("APP_ENV", "dev")
    app_version = os.getenv("APP_VERSION", "0.0.0")

    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": app_env,
            "service.version": app_version,
        }
    )

    # Create periodic reader + meter provider
    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=export_interval_millis,
    )

    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[reader],
    )
    set_meter_provider(_meter_provider)

    # Initialize sync Redis for gauge callbacks
    url = (
        redis_url
        if redis_url is not None
        else os.getenv("REDIS_URL") or "redis://localhost:6379"
    )
    _redis_client = redis.Redis.from_url(url, decode_responses=True)

    # Create meter and register instruments
    meter = _meter_provider.get_meter("tastytrade.metrics", "0.1.0")

    meter.create_observable_gauge(
        name="tastytrade.connection.status",
        description="Connection status per service (1=connected, 0=disconnected, -1=error)",
        callbacks=[observe_connection_status],
    )

    meter.create_observable_gauge(
        name="tastytrade.positions.count",
        description="Number of open positions in Redis",
        callbacks=[observe_position_count],
    )

    meter.create_observable_gauge(
        name="tastytrade.subscriptions.count",
        description="Number of active DXLink subscriptions",
        callbacks=[observe_subscription_count],
    )

    meter.create_observable_gauge(
        name="tastytrade.orders.count",
        description="Number of tracked orders in Redis",
        callbacks=[observe_order_count],
    )

    meter.create_observable_gauge(
        name="tastytrade.data.freshness_seconds",
        description="Age in seconds of the newest data per subscription type",
        callbacks=[observe_data_freshness],
    )

    _reconnection_counter = meter.create_counter(
        name="tastytrade.reconnections.total",
        description="Total reconnection events per service",
    )

    logger.info(
        "Metrics export initialized — endpoint=%s, interval=%dms",
        f"{endpoint}/v1/metrics",
        export_interval_millis,
    )

    return _meter_provider


def record_reconnection(service: str) -> None:
    """Record a reconnection event for a service.

    Args:
        service: Service name (e.g. "account_stream", "subscription").
    """
    if _reconnection_counter is not None:
        _reconnection_counter.add(1, {"service": service})  # type: ignore[union-attr]


def shutdown_metrics() -> None:
    """Gracefully shutdown the metrics pipeline, flushing pending data."""
    global _meter_provider, _redis_client

    if _meter_provider is not None:
        _meter_provider.force_flush()
        _meter_provider.shutdown()
        _meter_provider = None

    if _redis_client is not None:
        _redis_client.close()
        _redis_client = None


# ---------------------------------------------------------------------------
# Observable gauge callbacks
# ---------------------------------------------------------------------------


def observe_connection_status(options: CallbackOptions) -> Sequence[Observation]:
    """Read connection status for both streaming services from Redis."""
    if _redis_client is None:
        return []

    observations: list[Observation] = []
    services = [
        ("subscription", CONNECTION_KEY),
        ("account_stream", ACCOUNT_CONNECTION_KEY),
    ]

    for service_name, redis_key in services:
        try:
            status = _redis_client.hgetall(redis_key)
            state_str = (
                status.get("state", "disconnected") if status else "disconnected"
            )
            value = STATE_VALUES.get(str(state_str), -1)
            observations.append(Observation(value, {"service": service_name}))
        except Exception:
            observations.append(Observation(-1, {"service": service_name}))

    return observations


def observe_position_count(options: CallbackOptions) -> Sequence[Observation]:
    """Read the number of open positions from Redis."""
    if _redis_client is None:
        return []
    try:
        count = _redis_client.hlen(POSITIONS_KEY)
        return [Observation(count)]
    except Exception:
        return [Observation(0)]


def observe_subscription_count(options: CallbackOptions) -> Sequence[Observation]:
    """Read the number of active subscriptions from Redis."""
    if _redis_client is None:
        return []
    try:
        all_subs = _redis_client.hgetall(SUBSCRIPTIONS_KEY)
        active = 0
        for data_str in all_subs.values():
            try:
                data = json.loads(str(data_str))
                if data.get("active", False):
                    active += 1
            except (json.JSONDecodeError, TypeError):
                continue
        return [Observation(active)]
    except Exception:
        return [Observation(0)]


def observe_order_count(options: CallbackOptions) -> Sequence[Observation]:
    """Read the number of tracked orders from Redis."""
    if _redis_client is None:
        return []
    try:
        count = _redis_client.hlen(ORDERS_KEY)
        return [Observation(count)]
    except Exception:
        return [Observation(0)]


def observe_data_freshness(options: CallbackOptions) -> Sequence[Observation]:
    """Calculate age of newest data per subscription feed type.

    Reads last_update timestamps from subscription metadata and reports
    the minimum age (freshest) per feed type (Candle, Ticker).
    """
    if _redis_client is None:
        return []

    observations: list[Observation] = []
    now = time.time()

    try:
        all_subs = _redis_client.hgetall(SUBSCRIPTIONS_KEY)
        freshest: dict[str, float] = {}  # feed_type -> newest_timestamp

        for data_str in all_subs.values():
            try:
                data = json.loads(str(data_str))
                if not data.get("active", False):
                    continue

                last_update = data.get("last_update")
                if not last_update:
                    continue

                # Determine feed type from metadata
                metadata = data.get("metadata", {})
                feed_type = metadata.get("feed_type", "unknown")

                from datetime import datetime, timezone

                ts = (
                    datetime.fromisoformat(last_update)
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )

                if feed_type not in freshest or ts > freshest[feed_type]:
                    freshest[feed_type] = ts

            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        for feed_type, newest_ts in freshest.items():
            age_seconds = max(0.0, now - newest_ts)
            observations.append(Observation(age_seconds, {"feed_type": feed_type}))

    except Exception:
        pass

    return observations
