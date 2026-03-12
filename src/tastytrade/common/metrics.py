"""OTLP metrics export for system health observability in Grafana Cloud.

Architecture:
- Event-driven gauges set at the point of state change (no polling)
- Producers call set_*() functions when state changes
- MeterProvider with PeriodicExportingMetricReader pushes to Grafana Cloud
- No Redis dependency — metrics are emitted directly by the code that owns the state

Metrics exported:
- tastytrade.connection.status — gauge per service (1=connected, 0=disconnected, -1=error)
- tastytrade.positions.count — gauge of open positions
- tastytrade.subscriptions.count — gauge of active subscriptions
- tastytrade.orders.count — gauge of tracked orders
- tastytrade.reconnections.total — counter of reconnection events

Usage:
    from tastytrade.common.metrics import init_metrics, set_position_count
    init_metrics()

    # At the point of state change:
    set_position_count(5)
"""

import base64
import logging
import os
from typing import Optional

from typing import Any

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Counter, set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

# Module-level state
_meter_provider: Optional[MeterProvider] = None
_connection_gauge: Any = None  # OTel Gauge (type not publicly exported)
_positions_gauge: Any = None
_subscriptions_gauge: Any = None
_orders_gauge: Any = None
_reconnection_counter: Optional[Counter] = None

# Connection state mapping for numeric gauge values
STATE_VALUES = {"connected": 1, "disconnected": 0, "error": -1}


def init_metrics(
    export_interval_millis: int = 15000,
) -> Optional[MeterProvider]:
    """Initialize OTLP metrics export pipeline.

    Sets up gauges and counters that are updated directly by producers.
    A PeriodicExportingMetricReader pushes accumulated state to Grafana Cloud.

    Args:
        export_interval_millis: How often to export metrics to Grafana Cloud.

    Returns:
        The MeterProvider if initialized, None if credentials are missing.
    """
    global _meter_provider, _connection_gauge, _positions_gauge
    global _subscriptions_gauge, _orders_gauge, _reconnection_counter

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

    # Create meter and register instruments
    meter = _meter_provider.get_meter("tastytrade.metrics", "0.1.0")

    _connection_gauge = meter.create_gauge(
        name="tastytrade.connection.status",
        description="Connection status per service (1=connected, 0=disconnected, -1=error)",
    )

    _positions_gauge = meter.create_gauge(
        name="tastytrade.positions.count",
        description="Number of open positions",
    )

    _subscriptions_gauge = meter.create_gauge(
        name="tastytrade.subscriptions.count",
        description="Number of active DXLink subscriptions",
    )

    _orders_gauge = meter.create_gauge(
        name="tastytrade.orders.count",
        description="Number of tracked orders",
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


# ---------------------------------------------------------------------------
# Event-driven metric setters — called at the point of state change
# ---------------------------------------------------------------------------


def set_connection_status(service: str, state: str) -> None:
    """Record connection status change for a service.

    Args:
        service: Service name ("account_stream" or "subscription").
        state: Connection state ("connected", "disconnected", or "error").
    """
    if _connection_gauge is not None:
        value = STATE_VALUES.get(state, -1)
        _connection_gauge.set(value, {"service": service})


def set_position_count(count: int) -> None:
    """Record the current number of open positions."""
    if _positions_gauge is not None:
        _positions_gauge.set(count)


def set_subscription_count(count: int) -> None:
    """Record the current number of active subscriptions."""
    if _subscriptions_gauge is not None:
        _subscriptions_gauge.set(count)


def set_order_count(count: int) -> None:
    """Record the current number of tracked orders."""
    if _orders_gauge is not None:
        _orders_gauge.set(count)


def record_reconnection(service: str) -> None:
    """Record a reconnection event for a service.

    Args:
        service: Service name (e.g. "account_stream", "subscription").
    """
    if _reconnection_counter is not None:
        _reconnection_counter.add(1, {"service": service})


def shutdown_metrics() -> None:
    """Gracefully shutdown the metrics pipeline, flushing pending data."""
    global _meter_provider

    if _meter_provider is not None:
        _meter_provider.force_flush()
        _meter_provider.shutdown()
        _meter_provider = None
