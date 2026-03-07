# Observability

Non-blocking observability for AsyncIO trading services via Grafana Cloud + OpenTelemetry.

**Implementation:** `src/tastytrade/common/observability.py`

---

## Architecture

```
AsyncIO Trading Service
        |
Python Logging Queue (non-blocking, drops on overflow)
        |
Background Worker Thread
        |
    +---+---+
    |       |
  stdout  OTLP HTTP Exporter
  (JSON)    |
            Grafana Cloud (Loki)
```

**Key constraint:** The trading loop must never block on logging. All log records are enqueued via `put_nowait()` and dropped if the queue is full.

---

## Environment Variables

```bash
# Grafana Cloud OTLP
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-<region>.grafana.net/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
GRAFANA_CLOUD_INSTANCE_ID=<numeric>
GRAFANA_CLOUD_TOKEN=<token with logs:write scope>

# Service identification
OTEL_SERVICE_NAME=tastytrade-subscription
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=dev,service.version=1.0.0

# Application
APP_ENV=dev
APP_VERSION=1.0.0
LOG_LEVEL=INFO
LOG_QUEUE_MAXSIZE=2000
```

Auth header is constructed as `Basic base64(instance_id:token)`.

Variables must be set before `init_observability()` is called. In Docker, use `env_file:` in compose. On host, `source .env` before running.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Root logger replacement | Zero changes to existing code — all loggers inherit |
| Auto-enable on token presence | Graceful fallback when Grafana not configured |
| Queue drop on overflow | Trading safety — never block the event loop |
| Daemon thread | Automatic cleanup on process exit |
| No Alloy (Phase 1) | Single host, low volume — direct OTLP is sufficient |
| No local Loki | CPU/disk/WAL overhead not justified for single host |

---

## Logging Policy

**Log state transitions:** `session_started`, `order_submitted`, `order_filled`, `order_rejected`, `risk_check_failed`, `feed_disconnected`

**Never log:** tick-level data, per-loop iterations, raw payloads, PII (account numbers, balances)

---

## Grafana Cloud Queries

```
{service_name="tastytrade-subscription"}
{service_name="tastytrade-subscription"} |= "ERROR"
{service_name="tastytrade-subscription"} | json | name="orchestrator"
{deployment_environment="prod"}
```
