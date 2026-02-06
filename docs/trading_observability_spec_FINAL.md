# Trading App Observability Spec (Final Production Version)

Grafana Cloud + OpenTelemetry + JSON Logging

------------------------------------------------------------------------

# Purpose

Provide a **safe, fire‑and‑forget observability architecture** for an
AsyncIO‑based trading application using:

• Grafana Cloud Logs (Loki) • OpenTelemetry OTLP Export • Structured
JSON logging • Non‑blocking queue design

------------------------------------------------------------------------

# 1. Final Architecture (LOCKED)

    AsyncIO Trading Service
            ↓
    Python Logging Queue (non‑blocking)
            ↓
    Background Worker Thread
            ↓
    OpenTelemetry LoggingHandler + Batch Processor
            ↓
    OTLP HTTP Exporter
            ↓
    Grafana Cloud OTLP Gateway
            ↓
    Grafana Loki Cloud Logs

------------------------------------------------------------------------

# 2. Design Guarantees

  Guarantee                    Mechanism
  ---------------------------- --------------------------------------
  Trading loop never blocked   Queue + drop‑on‑overflow
  AsyncIO safe                 Export isolated in background thread
  Cloud persistence            OTLP batching + retries
  Local debugging visibility   JSON logs to stdout
  Graceful shutdown            Queue drain + provider flush

------------------------------------------------------------------------

# 3. Why NOT Alloy or Local Loki (Phase 1)

### Alloy

Reserved for:

• Multi‑host routing • Centralized redaction • Advanced routing rules

### Local Loki

Rejected due to:

• CPU overhead • Disk/WAL retention complexity • Operational fragility

------------------------------------------------------------------------

# 4. Grafana Cloud Requirements

## Required Inputs

### OTLP Endpoint

    https://otlp-gateway-prod-<region>.grafana.net/otlp

### OTLP Logs Path

    /v1/logs

### Instance ID

Numeric identifier from Grafana stack

### Access Policy Token

Minimum scope:

    logs:write

### Authorization Header Construction

    base64(instance_id:token)

------------------------------------------------------------------------

# 5. Environment Variables (Standard)

    OTEL_EXPORTER_OTLP_ENDPOINT
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf

    GRAFANA_CLOUD_INSTANCE_ID
    GRAFANA_CLOUD_TOKEN

    OTEL_LOGS_EXPORTER=otlp

    OTEL_SERVICE_NAME
    OTEL_RESOURCE_ATTRIBUTES

    APP_NAME
    APP_ENV
    APP_VERSION
    LOG_LEVEL
    LOG_QUEUE_MAXSIZE=2000

------------------------------------------------------------------------

# 6. Python Dependencies

    pip install \
      opentelemetry-sdk \
      opentelemetry-exporter-otlp-proto-http \
      python-json-logger

------------------------------------------------------------------------

# 7. Lockbox Ownership Model (MANDATORY)

The observability module:

• Lives in shared platform package\
• Must NOT be rewritten by service teams\
• Only platform maintainers modify it

------------------------------------------------------------------------

# 8. Final observability.py Implementation

``` python
# observability.py
"""
Non-blocking observability module for trading applications.

Architecture:
- Main thread enqueues log records (never blocks)
- Background thread handles stdout + OTLP export
- Graceful degradation: drops logs if queue full
"""

import atexit
import base64
import logging
import os
import queue
import sys
import threading
from typing import Optional

from pythonjsonlogger import jsonlogger

from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter


_log_queue: Optional[queue.Queue] = None
_listener_thread: Optional[threading.Thread] = None
_shutdown_event: Optional[threading.Event] = None
_logger_provider: Optional[LoggerProvider] = None


def init_observability() -> None:
    """
    Initialize observability with non-blocking queue-based logging.

    Safe to call multiple times (idempotent).
    Must be called before any logging in the application.
    """
    global _log_queue, _listener_thread, _shutdown_event, _logger_provider

    if _listener_thread is not None:
        return  # Already initialized

    # Create queue for non-blocking log handoff
    max_size = int(os.getenv("LOG_QUEUE_MAXSIZE", "2000"))
    _log_queue = queue.Queue(maxsize=max_size)
    _shutdown_event = threading.Event()

    # Configure root logger to use queue handler
    root_logger = logging.getLogger()
    root_logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    root_logger.handlers.clear()
    root_logger.addHandler(_QueueHandler(_log_queue))

    # Initialize OTEL provider (needed before starting worker)
    _logger_provider = _create_otel_provider()

    # Start background worker thread
    _listener_thread = threading.Thread(
        target=_listener_worker,
        name="observability-worker",
        daemon=True,
    )
    _listener_thread.start()

    # Register shutdown handler
    atexit.register(shutdown_observability)


def shutdown_observability() -> None:
    """Gracefully shutdown observability, flushing pending logs."""
    global _shutdown_event, _logger_provider

    if _shutdown_event is not None:
        _shutdown_event.set()

    if _logger_provider is not None:
        _logger_provider.force_flush()
        _logger_provider.shutdown()


def _create_otel_provider() -> LoggerProvider:
    """Create and configure the OpenTelemetry LoggerProvider."""

    # Build resource attributes for service identification
    service_name = os.getenv("OTEL_SERVICE_NAME", "tastytrade")
    app_env = os.getenv("APP_ENV", "dev")
    app_version = os.getenv("APP_VERSION", "0.0.0")

    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": app_env,
        "service.version": app_version,
    })

    # Build authorization header
    instance_id = os.getenv("GRAFANA_CLOUD_INSTANCE_ID", "")
    token = os.getenv("GRAFANA_CLOUD_TOKEN", "")

    headers = {}
    if instance_id and token:
        auth_string = f"{instance_id}:{token}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode()
        headers["Authorization"] = f"Basic {auth_b64}"

    # Create OTLP exporter
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    exporter = OTLPLogExporter(
        endpoint=f"{endpoint}/v1/logs" if endpoint else None,
        headers=headers,
        timeout=5,
    )

    # Create provider with batching processor
    provider = LoggerProvider(resource=resource)

    processor = BatchLogRecordProcessor(
        exporter,
        max_queue_size=2048,
        max_export_batch_size=512,
        schedule_delay_millis=1000,
        export_timeout_millis=5000,
    )
    provider.add_log_record_processor(processor)

    # Set as global provider
    set_logger_provider(provider)

    return provider


class _QueueHandler(logging.Handler):
    """
    Non-blocking handler that enqueues records for background processing.

    If queue is full, log is silently dropped (trading safety).
    """

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait(record)
        except queue.Full:
            # Drop log rather than block trading loop
            pass


def _listener_worker() -> None:
    """
    Background worker that processes log records.

    Outputs to:
    1. stdout (JSON format for local visibility / container logs)
    2. OTLP exporter (batched to Grafana Cloud)
    """
    global _log_queue, _shutdown_event, _logger_provider

    # Setup stdout handler with JSON formatting
    stdout_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    stdout_handler.setFormatter(formatter)

    # Create a dedicated logger for stdout (prevents recursion)
    stdout_logger = logging.getLogger("_observability_stdout")
    stdout_logger.handlers.clear()
    stdout_logger.addHandler(stdout_handler)
    stdout_logger.setLevel(logging.DEBUG)
    stdout_logger.propagate = False

    # Create OTEL logging handler bridged to our provider
    otel_handler = LoggingHandler(logger_provider=_logger_provider)

    # Process queue until shutdown
    while not _shutdown_event.is_set():
        try:
            # Use timeout to allow checking shutdown event
            record = _log_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        try:
            # Output 1: JSON to stdout (local visibility)
            stdout_logger.handle(record)

            # Output 2: OTLP to Grafana Cloud
            otel_handler.emit(record)

        except Exception:
            # Never let logging errors crash the worker
            pass
        finally:
            _log_queue.task_done()

    # Drain remaining logs on shutdown
    while not _log_queue.empty():
        try:
            record = _log_queue.get_nowait()
            stdout_logger.handle(record)
            otel_handler.emit(record)
            _log_queue.task_done()
        except queue.Empty:
            break
```

------------------------------------------------------------------------

# 9. Service Usage Pattern

``` python
from observability import init_observability
import logging

init_observability()

logger = logging.getLogger("trade-exec")
logger.info("service_started")
```

------------------------------------------------------------------------

# 10. Smoke Test Script

``` python
from observability import init_observability
import logging
import time

init_observability()

logger = logging.getLogger("observability-test")

for i in range(5):
    logger.info("grafana_smoke_test", extra={"iteration": i})
    time.sleep(1)
```

------------------------------------------------------------------------

# 11. Logging Policy (Trading Safe)

### Allowed Events

• session_started • order_submitted • order_filled • order_rejected •
risk_check_failed • feed_disconnected

### Forbidden

• Tick level logging • Per‑loop logging • Raw payload dumps

------------------------------------------------------------------------

# 12. Definition of Done

• Logs visible in Docker stdout\
• Logs visible in Grafana Cloud\
• Logging cannot block trading loop\
• Module centralized in platform package\
• Smoke test passes

------------------------------------------------------------------------

# 13. Future Extensions (Out of Scope)

• Metrics • Tracing • Alloy deployment • Alert automation • Data science
pipelines

------------------------------------------------------------------------

# Appendix --- Revision Notes

### v3 Final Production Version

• Correct OTLP `/v1/logs` endpoint • Proper LoggingHandler bridge •
Resource attributes added • Graceful shutdown support • Auth header
construction fixed • Queue‑safe non‑blocking design
