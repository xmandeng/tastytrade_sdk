# Grafana Cloud Logging (Dead-Simple) for AsyncIO Trading App

**Scope:** Centralized application logs only (session mgmt, events,
order lifecycle, errors)\
**Non-goals:** tick logging, metrics/tracing (can be added later),
running Loki/Alloy locally, local log files

------------------------------------------------------------------------

## 0) Why this design (rationale, in plain terms)

### What we want

-   "Fire-and-forget" logging that **never** blocks the trading loop.
-   Minimal moving parts: **no agent**, **no Loki container**, no local
    storage/indexing.
-   Structured JSON logs for easy search in Grafana Cloud.
-   Low volume (≤ \~60 logs/min in high water) → direct cloud ingestion
    is safe and cheap.

### Why we are not using Grafana Alloy right now

-   We run Docker on **one host** and have low log volume.
-   Alloy is a great production collector, but it adds:
    -   another container to deploy/monitor
    -   configuration complexity
-   We may add Alloy later if we need centralized
    filtering/redaction/routing or multiple hosts.

### Why we are not running Loki locally

-   Loki can "blow up" on a single host due to
    disk/WAL/retention/indexing/compaction overhead.
-   Grafana Cloud avoids local storage and operational overhead
    entirely.

------------------------------------------------------------------------

## 1) Architecture (minimal)

    AsyncIO Python service (in Docker)
      -> JSON logs to stdout (for local visibility)
      -> in-process enqueue (fast, non-blocking)
      -> background worker exports via OTLP/HTTP
      -> Grafana Cloud OTLP endpoint
      -> Loki (Grafana Cloud Logs)

------------------------------------------------------------------------

## 2) Grafana Cloud prerequisites

1)  OTLP HTTP endpoint\
2)  Instance ID (numeric)\
3)  Access Policy Token (`logs:write` scope)\
4)  Authorization header:
    `Authorization: Basic base64(instance_id:token)`

------------------------------------------------------------------------

## 3) Standard environment variables

``` bash
OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp-gateway-prod-<region>.grafana.net/otlp"
OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <BASE64(instance_id:token)>"

OTEL_LOGS_EXPORTER="otlp"
OTEL_SERVICE_NAME="trade-exec"
OTEL_RESOURCE_ATTRIBUTES="deployment.environment=prod,team=trading,service.version=1.0.0"

LOG_LEVEL="INFO"
APP_ENV="prod"
APP_NAME="trade-exec"
APP_VERSION="1.0.0"
```

------------------------------------------------------------------------

## 4) Python dependencies

``` bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp python-json-logger
```

------------------------------------------------------------------------

## 5) observability.py

(Shared module for JSON logging + OTLP export)

``` python
# See full source in original spec (unchanged)
```

------------------------------------------------------------------------

## 6) Usage

``` python
from observability import init_observability
import logging

init_observability()

logger = logging.getLogger("trade-exec")
logger.info("service_started", extra={"component": "startup"})
```

------------------------------------------------------------------------

## 7) Logging conventions

### Event naming

-   `session_created`
-   `order_submitted`
-   `order_rejected`
-   `feed_disconnected`

### Context fields

-   `run_id`, `session_id`, `strategy_id`, `order_id`, `symbol`,
    `component`

### Never label in Loki

-   `order_id`
-   `run_id`
-   `correlation_id`

------------------------------------------------------------------------

## 8) Docker Compose example

``` yaml
services:
  trade-exec:
    image: yourorg/trade-exec:latest
    environment:
      APP_NAME: trade-exec
      APP_ENV: prod
      APP_VERSION: "1.0.0"
      LOG_LEVEL: INFO

      OTEL_LOGS_EXPORTER: otlp
      OTEL_SERVICE_NAME: trade-exec
      OTEL_RESOURCE_ATTRIBUTES: deployment.environment=prod,team=trading,service.version=1.0.0

      OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf
      OTEL_EXPORTER_OTLP_ENDPOINT: "https://otlp-gateway-prod-<region>.grafana.net/otlp"
      OTEL_EXPORTER_OTLP_HEADERS: "Authorization=Basic <BASE64(instance_id:token)>"
```

------------------------------------------------------------------------

## 9) Verification checklist

### Grafana UI

-   Explore → Logs
-   Query `{}` or `{service_name="trade-exec"}`

### Smoke test

``` python
logger.error("grafana_smoke_test")
```

------------------------------------------------------------------------

## 10) Definition of Done

-   observability module integrated
-   Logs visible in Docker + Grafana
-   No tick-level logging
-   Credentials managed securely
-   No exporter blocking trading loop

------------------------------------------------------------------------

## 11) Future extension

-   Add tracing
-   Add dashboards/alerts
-   Add Alloy if multi-host scaling required
