# Observability

Non-blocking observability for AsyncIO trading services via Grafana Cloud + OpenTelemetry.

**Implementation:**
- Logs: `src/tastytrade/common/observability.py`
- Metrics: `src/tastytrade/common/metrics.py`

---

## Architecture

```
AsyncIO Trading Service
        |
   +----+----+
   |         |
 Logging   Metrics
   |         |
Queue     Observable Gauges (sync Redis callbacks)
   |         |
Worker    PeriodicExportingMetricReader
   |         |
+--+--+      |
|     |      |
stdout OTLP  OTLP
(JSON)  |     |
     Grafana Cloud
     (Loki)  (Mimir)
```

**Key constraints:**
- The trading loop must never block on logging — records enqueued via `put_nowait()`, dropped if full
- Metrics use a separate sync Redis connection — gauge callbacks never touch the async event loop

---

## Environment Variables

```bash
# Grafana Cloud OTLP
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-<region>.grafana.net/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
GRAFANA_CLOUD_INSTANCE_ID=<numeric>
GRAFANA_CLOUD_TOKEN=<token with logs:write scope>

# Grafana Cloud Metrics (Mimir) — separate instance
GRAFANA_CLOUD_METRICS_INSTANCE_ID=<numeric>
GRAFANA_CLOUD_METRICS_TOKEN=<token with metrics:write scope>

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
| Sync Redis for metrics | Gauge callbacks run in SDK thread, not async loop — separate connection avoids event loop coupling |
| Observable gauges | Read-only from Redis — no metrics state to manage, always reflects current system state |
| Separate metrics credentials | Grafana Cloud uses different instances for Loki (logs) vs Mimir (metrics) |

---

## Logging Policy

**Log state transitions:** `session_started`, `order_submitted`, `order_filled`, `order_rejected`, `risk_check_failed`, `feed_disconnected`

**Never log:** tick-level data, per-loop iterations, raw payloads, PII (account numbers, balances)

---

## Metrics

| Metric | Type | Description | Attributes |
|--------|------|-------------|------------|
| `tastytrade.connection.status` | Gauge | 1=connected, 0=disconnected, -1=error | `service` |
| `tastytrade.positions.count` | Gauge | Open positions in Redis | — |
| `tastytrade.subscriptions.count` | Gauge | Active DXLink subscriptions | — |
| `tastytrade.orders.count` | Gauge | Tracked orders in Redis | — |
| `tastytrade.data.freshness_seconds` | Gauge | Age of newest data per feed type | `feed_type` |
| `tastytrade.reconnections.total` | Counter | Reconnection events | `service` |

Observable gauges read from Redis on each collection cycle (default 15s). The reconnection counter is incremented by orchestrators via `record_reconnection()`.

---

## Grafana Cloud Queries

### Logs (Loki)

```
{service_name="tastytrade-subscription"}
{service_name="tastytrade-subscription"} |= "ERROR"
{service_name="tastytrade-subscription"} | json | name="orchestrator"
{deployment_environment="prod"}
```

### Metrics (Mimir / PromQL)

```promql
tastytrade_connection_status{service="subscription"}
tastytrade_positions_count
tastytrade_subscriptions_count
tastytrade_data_freshness_seconds{feed_type="Ticker"}
rate(tastytrade_reconnections_total[5m])
```
