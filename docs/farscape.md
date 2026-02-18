# Farscape: AWS Container Migration

**Project:** Migrate the tastytrade-sdk infrastructure from local Docker Compose
to AWS container services.

**Guiding principle:** The current architecture is sound. Redis pub/sub for
real-time fire-and-forget delivery. Telegraf → InfluxDB for durable time-series
writes. Grafana Cloud for observability. Farscape is a *lift* — not a redesign.

---

## 1. Architectural Overview

### Current State (Local Docker Compose)

Everything runs on a single host via `docker-compose.yml`. The Python app runs
either on the host or inside the devcontainer, connecting to services over
`localhost` (port-mapped) or Docker DNS (`internal_net` bridge).

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                             │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │              docker-compose (internal_net)              │   │
│   │                                                         │   │
│   │   ┌───────────┐  ┌──────────┐  ┌───────┐  ┌─────────┐  │   │
│   │   │ InfluxDB  │  │ Telegraf │  │ Redis │  │ Grafana │  │   │
│   │   │  :8086    │  │  :8186   │  │ :6379 │  │  :3000  │  │   │
│   │   └───────────┘  └──────────┘  └───────┘  └─────────┘  │   │
│   │                                                         │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │          Python App (host or devcontainer)              │   │
│   │                                                         │   │
│   │   tasty-subscription    FastAPI     HullMacdEngine      │   │
│   │   (DXLink WebSocket)    (API)       (Signal Detection)  │   │
│   │                                                         │   │
│   │   Processors: TelegrafHTTP → POST :8186                 │   │
│   │               Redis        → PUBLISH :6379              │   │
│   │               Signal       → Engine → emit → chain      │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Target State (AWS)

The same services, but deployed on managed AWS infrastructure. Grafana moves
fully to Grafana Cloud (already spec'd). Redis moves to ElastiCache. InfluxDB
and Telegraf run as ECS tasks. The Python app runs on ECS Fargate.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              AWS VPC                                     │
│                                                                          │
│   ┌──────────────── Private Subnets ────────────────────────────────┐    │
│   │                                                                  │    │
│   │   ┌──────────────────────────────┐    ┌───────────────────────┐  │    │
│   │   │  ECS Fargate: App Service    │    │  ECS Fargate: Data    │  │    │
│   │   │                              │    │                       │  │    │
│   │   │  ┌────────────────────────┐  │    │  ┌─────────────────┐  │  │    │
│   │   │  │ tasty-subscription     │  │    │  │    InfluxDB     │  │  │    │
│   │   │  │ (DXLink + processors) │──┼──POST──▶│    (ECS)       │  │  │    │
│   │   │  └────────────────────────┘  │    │  └─────────────────┘  │  │    │
│   │   │  ┌────────────────────────┐  │    │         ▲             │  │    │
│   │   │  │ FastAPI (optional)     │  │    │  ┌──────┴──────────┐  │  │    │
│   │   │  └────────────────────────┘  │    │  │   Telegraf      │  │  │    │
│   │   │  ┌────────────────────────┐  │    │  │   (sidecar)     │  │  │    │
│   │   │  │ HullMacdEngine        │  │    │  └─────────────────┘  │  │    │
│   │   │  └────────────────────────┘  │    └───────────────────────┘  │    │
│   │   │              │               │                               │    │
│   │   │          PUBLISH             │                               │    │
│   │   │              ▼               │                               │    │
│   │   │   ┌────────────────────┐     │                               │    │
│   │   │   │  ElastiCache Redis │     │                               │    │
│   │   │   │  (Serverless)      │     │                               │    │
│   │   │   └────────────────────┘     │                               │    │
│   │   │                              │                               │    │
│   │   └──────────────────────────────┴───────────────────────────────┘    │
│   │                                                                       │
│   │   ┌───────────────────────────────────────────────────────────────┐   │
│   │   │                    Secrets Manager                            │   │
│   │   │  TastyTrade creds, InfluxDB token, Grafana token, etc.       │   │
│   │   └───────────────────────────────────────────────────────────────┘   │
│   │                                                                       │
│   └───────────────────────────────────────────────────────────────────────┘
│                                                                          │
│                          ┌──────────────────┐                            │
│                          │   CloudWatch      │                           │
│                          │   (container logs) │                           │
│                          └──────────────────┘                            │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

                    ┌──────────────────────────┐
                    │    Grafana Cloud          │
                    │                          │
                    │  Loki  (logs via OTLP)   │
                    │  Dashboards              │
                    └──────────────────────────┘

                    ┌──────────────────────────┐
                    │   DXFeed (external)       │
                    │   WebSocket endpoint      │
                    └──────────────────────────┘
```

### Data Flow (Unchanged)

The pipeline topology is identical to local. Only the transport addresses change.

```
DXFeed WebSocket
       │
       ▼
┌──────────────┐
│ DXLinkManager│   ECS Fargate: App Service
│ (WebSocket)  │
└──────┬───────┘
       │ raw JSON
       ▼
┌──────────────┐
│ EventHandler │
│   .queue     │
└──────┬───────┘
       │ typed CandleEvent / QuoteEvent
       ▼
┌──────────────────────────────────────┐
│         Processor Pipeline           │
│                                      │
│  ┌─────────────────────────────────┐ │
│  │ TelegrafHTTPEventProcessor      │ │──── POST ───▶ Telegraf :8186 ──▶ InfluxDB
│  └─────────────────────────────────┘ │              (sidecar in data task)
│  ┌─────────────────────────────────┐ │
│  │ RedisEventProcessor             │ │──── PUBLISH ─▶ ElastiCache Redis
│  └─────────────────────────────────┘ │               (fire-and-forget)
│  ┌─────────────────────────────────┐ │
│  │ SignalEventProcessor            │ │──── engine ──▶ TradeSignal
│  └─────────────────────────────────┘ │               └─▶ re-emit into chain
│                                      │
└──────────────────────────────────────┘
```

---

## 2. Component Mapping

What changes and what stays the same:

| Component | Local (Today) | AWS (Farscape) | Change Type |
|-----------|--------------|----------------|-------------|
| **Python app** | Host / devcontainer | ECS Fargate task | Containerize + deploy |
| **Redis** | `redis:7-alpine` container | ElastiCache Serverless | Replace with managed |
| **InfluxDB** | `influxdb:2.7.1` container | ECS Fargate task + EBS | Containerize (self-managed) |
| **Telegraf** | `telegraf:1.25.0` container | Sidecar in InfluxDB task | Co-locate |
| **Grafana** | `grafana:latest` container | Grafana Cloud | Replace with SaaS |
| **Redis Commander** | `redis-commander` container | Drop | Not needed in prod |
| **Observability** | JSON stdout | OTLP → Grafana Cloud | Already spec'd (TT-23) |
| **Secrets** | `.env` file | AWS Secrets Manager | Secure rotation |
| **Service discovery** | Docker DNS / localhost | VPC DNS + env vars | Same layered pattern |
| **Networking** | `internal_net` bridge | VPC private subnets | Same isolation model |

### Why ElastiCache Serverless for Redis

- Zero capacity planning — scales to your pub/sub load automatically
- No node management, patching, or failover configuration
- Sub-millisecond latency for pub/sub (same as self-managed)
- Pay-per-use — ideal for a market-hours-only workload
- Supports pub/sub natively (unlike MemoryDB which is durability-focused)

### Why Self-Managed InfluxDB on ECS (not Amazon Timestream)

- Timestream uses SQL-like query language — your codebase uses Flux/InfluxQL
- Zero migration effort: same `influxdb:2.7.1` image, same Telegraf config
- Direct compatibility with existing `influxdb-client` Python SDK
- EBS volume for persistence across task restarts

---

## 3. AWS Infrastructure Components

### VPC Layout

```
┌──────────────────────── VPC (10.0.0.0/16) ────────────────────────┐
│                                                                     │
│  ┌─── Public Subnet (AZ-a) ───┐  ┌─── Public Subnet (AZ-b) ───┐   │
│  │  NAT Gateway                │  │  (NAT GW for HA, optional)  │   │
│  └─────────────────────────────┘  └──────────────────────────────┘   │
│                                                                     │
│  ┌── Private Subnet (AZ-a) ───┐  ┌── Private Subnet (AZ-b) ───┐   │
│  │                             │  │                              │   │
│  │  ECS: App Service           │  │  (standby for HA, optional)  │   │
│  │  ECS: Data Service          │  │                              │   │
│  │  ElastiCache Redis          │  │                              │   │
│  │                             │  │                              │   │
│  └─────────────────────────────┘  └──────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Single-AZ is fine for Phase 1.** This is a market data analytics workload,
not a customer-facing SLA. Multi-AZ adds cost and complexity with no
meaningful benefit yet.

### ECS Cluster

Two task definitions, both Fargate:

**Task 1: App Service** (the Python workload)
- Container: `tastytrade-app` (built from production Dockerfile stage)
- CPU: 0.5 vCPU, Memory: 1 GB (start small, adjust)
- Entry point: `uv run tasty-subscription run --symbols SPX,NVDA,SPY ...`
- Outbound: DXFeed WebSocket (internet via NAT), Telegraf (port 8186), Redis (port 6379)
- Env vars: injected from Secrets Manager + task definition

**Task 2: Data Service** (InfluxDB + Telegraf sidecar)
- Container A: `influxdb:2.7.1` — port 8086, EBS-backed volume
- Container B: `telegraf:1.25.0` — port 8186, same task (localhost access to InfluxDB)
- CPU: 1 vCPU, Memory: 2 GB
- Storage: EBS volume mounted at `/var/lib/influxdb2`

```
┌─────────── ECS Task: Data Service ──────────────┐
│                                                   │
│  ┌─────────────┐      ┌──────────────────────┐   │
│  │  Telegraf    │      │     InfluxDB         │   │
│  │  :8186      │─────▶│     :8086            │   │
│  │  (HTTP in)   │ localhost  (time-series DB)  │   │
│  └─────────────┘      └──────────────────────┘   │
│                              │                    │
│                        ┌─────┴─────┐              │
│                        │ EBS Vol   │              │
│                        │ /influxdb │              │
│                        └───────────┘              │
│                                                   │
└───────────────────────────────────────────────────┘
```

Telegraf as a sidecar means it reaches InfluxDB over `localhost` within the
same task — identical to the current Docker Compose `internal_net` setup.
The existing `telegraf.conf` works with one URL change:
`http://influxdb:8086` → `http://localhost:8086`.

### Secrets Manager

| Secret | Maps To |
|--------|---------|
| `tastytrade/credentials` | `TASTY_USERNAME`, `TASTY_PASSWORD` |
| `tastytrade/influxdb` | `INFLUX_DB_TOKEN`, `INFLUX_DB_ORG`, `INFLUX_DB_BUCKET` |
| `tastytrade/grafana` | `GRAFANA_CLOUD_INSTANCE_ID`, `GRAFANA_CLOUD_TOKEN` |
| `tastytrade/dxfeed` | `DXFEED_TOKEN` (if separate from TastyTrade auth) |

ECS natively injects Secrets Manager values as environment variables — no
application code changes needed. Your existing `os.environ` resolution
layer works as-is.

---

## 4. What Changes in Code

Almost nothing.

### Service Discovery (Already Solved)

Your layered resolution (`os.environ` → Redis → code default) was designed
for exactly this scenario. In ECS, the task definition sets environment
variables the same way Docker Compose does:

```
Local Docker Compose              ECS Task Definition
─────────────────────             ─────────────────────
environment:                      environment:
  REDIS_HOST: redis                 - name: REDIS_HOST
  INFLUX_DB_URL: ...                  value: <elasticache-endpoint>
                                    - name: INFLUX_DB_URL
                                      value: http://localhost:8086
```

The Python code doesn't know or care which environment it's in.

### Telegraf Config

One line change in `deploy/telegraf.conf`:

```diff
 [[outputs.influxdb_v2]]
-  urls = ["http://influxdb:8086"]
+  urls = ["http://localhost:8086"]
```

Because Telegraf is now a sidecar in the same ECS task as InfluxDB, they
share `localhost`. (Alternatively, keep the Docker DNS name and use ECS
service connect — but localhost is simpler.)

### Production Dockerfile

The existing `.devcontainer/Dockerfile` already has a `production` stage:

```dockerfile
FROM base AS production
# No dev tools installed
# Only runtime dependencies from base stage
```

This needs to be fleshed out to install the app and set an entry point:

```dockerfile
FROM base AS production

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run"]
CMD ["tasty-subscription", "run"]
```

### Everything Else

No changes to:
- Event processors
- WebSocket client
- Signal detection engine
- Redis pub/sub publish/subscribe logic
- InfluxDB client code
- Observability module (already targets Grafana Cloud)

---

## 5. Migration Plan

### Phase 0: Pre-Flight (Local)

Validate the production container works locally before touching AWS.

| Step | Action | Validation |
|------|--------|------------|
| 0.1 | Flesh out `production` stage in Dockerfile | `docker build --target production -t tastytrade-app .` builds clean |
| 0.2 | Create `docker-compose.prod.yml` that mirrors the AWS topology | All services start, app connects to Redis + Telegraf + InfluxDB |
| 0.3 | Test with `REDIS_HOST`, `INFLUX_DB_URL` env overrides | App connects via injected env vars, not defaults |
| 0.4 | Run `tasty-subscription` in production container for a market session | Candles flow through Telegraf → InfluxDB, signals fire, Redis pub/sub works |

```yaml
# docker-compose.prod.yml — local simulation of AWS topology
services:
  app:
    build:
      context: .
      dockerfile: .devcontainer/Dockerfile
      target: production
    environment:
      REDIS_HOST: redis
      INFLUX_DB_URL: http://data:8086
      TELEGRAF_URL: http://data:8186
    depends_on: [redis, data]

  data:
    # InfluxDB + Telegraf in one service (simulates ECS sidecar)
    # Use a custom compose with both, or test separately

  redis:
    image: redis:7-alpine
```

### Phase 1: AWS Foundation

Stand up the AWS infrastructure. No app deployment yet.

| Step | Action | Validation |
|------|--------|------------|
| 1.1 | Create VPC with public + private subnets (single AZ) | `aws ec2 describe-vpcs` |
| 1.2 | Create NAT Gateway in public subnet | Private subnet can reach internet |
| 1.3 | Create ElastiCache Serverless Redis | `redis-cli -h <endpoint> ping` from a bastion/Cloud9 |
| 1.4 | Create ECS cluster (Fargate) | Cluster visible in console |
| 1.5 | Create ECR repository for `tastytrade-app` | `docker push` succeeds |
| 1.6 | Store secrets in Secrets Manager | Secrets retrievable via CLI |
| 1.7 | Create EBS volume for InfluxDB data | Volume in target AZ |
| 1.8 | Create IAM roles (ECS task execution + task role) | Roles with Secrets Manager read + ECR pull + CloudWatch logs |

**IaC recommendation:** CDK (Python). You're already in a Python ecosystem —
CDK keeps infrastructure in the same language with type-safe constructs.
Terraform is also fine if you prefer it.

### Phase 2: Data Service Deployment

Deploy InfluxDB + Telegraf first because the app depends on them.

| Step | Action | Validation |
|------|--------|------------|
| 2.1 | Create ECS task definition for Data Service (InfluxDB + Telegraf sidecar) | Task registers |
| 2.2 | Create ECS service for Data Service (desired count: 1) | Task starts, InfluxDB healthy |
| 2.3 | Configure service discovery (Cloud Map) for `data.farscape.local` | DNS resolves within VPC |
| 2.4 | Verify Telegraf can write to InfluxDB (POST test data to :8186) | Data appears in InfluxDB |

### Phase 3: App Service Deployment

| Step | Action | Validation |
|------|--------|------------|
| 3.1 | Build + push `tastytrade-app` image to ECR | Image in ECR |
| 3.2 | Create ECS task definition for App Service | Task registers |
| 3.3 | Inject env vars: `REDIS_HOST=<elasticache>`, `TELEGRAF_URL=http://data.farscape.local:8186` | — |
| 3.4 | Create ECS service (desired count: 1) | Task starts, DXLink connects |
| 3.5 | Monitor CloudWatch logs for candle events flowing | Logs show event processing |
| 3.6 | Verify InfluxDB receives data via Telegraf | Flux query returns recent candles |
| 3.7 | Verify Redis pub/sub distributes events | `redis-cli SUBSCRIBE market:*` receives events |

### Phase 4: Observability + Hardening

| Step | Action | Validation |
|------|--------|------------|
| 4.1 | Enable OTLP → Grafana Cloud (set env vars) | Logs visible in Grafana Loki |
| 4.2 | Import Grafana dashboards (from `deploy/visualizations/`) | SPX dashboard renders |
| 4.3 | Configure CloudWatch alarms (task health, CPU, memory) | Alarms fire on test threshold |
| 4.4 | Test container restart recovery (kill task, verify ECS relaunches) | Auto-recovery works |
| 4.5 | Test WebSocket reconnection after network blip | DXLink reconnects, data resumes |

---

## 6. Cost Estimate (Ballpark)

For a single-instance, market-hours-only workload (~7h/day, 5 days/week):

| Service | Estimate (monthly) | Notes |
|---------|-------------------|-------|
| ECS Fargate (App) | ~$15–25 | 0.5 vCPU, 1 GB, ~150h/month |
| ECS Fargate (Data) | ~$25–40 | 1 vCPU, 2 GB, ~150h/month |
| ElastiCache Serverless | ~$10–20 | Minimal data, pub/sub only |
| NAT Gateway | ~$35 + data | Fixed cost — this is the pricey one |
| EBS (InfluxDB) | ~$5–10 | 50 GB gp3 |
| ECR | ~$1 | Image storage |
| Secrets Manager | ~$2 | 4 secrets |
| CloudWatch Logs | ~$5 | Log ingestion |
| **Total** | **~$100–140/mo** | |

The NAT Gateway is the largest fixed cost. If you want to optimize:
- Schedule ECS tasks to start/stop with market hours (EventBridge rule)
- Consider a NAT instance (t4g.nano, ~$3/mo) instead of NAT Gateway for
  a non-production workload

---

## 7. What We're NOT Doing

| Temptation | Why Not |
|-----------|---------|
| Multi-AZ | Single user, analytics workload. Not worth the cost/complexity yet. |
| ALB / API Gateway | No inbound HTTP traffic from the internet. App is outbound-only (DXFeed WebSocket). |
| EKS / Kubernetes | Massive overkill. Two Fargate tasks don't need an orchestrator. |
| Amazon Timestream | Different query language, migration effort for zero benefit. |
| Kafka / MSK | Already validated — Redis pub/sub is the right tool for fire-and-forget. |
| Lambda | WebSocket connections are long-lived. Lambda's 15-min timeout doesn't fit. |
| Auto-scaling | Single instance is fine. Scale decisions come later if needed. |
| CI/CD pipeline | Manual deploy first. Automate when the deployment is proven stable. |

---

## 8. Rollback Strategy

At every phase, the local Docker Compose environment remains fully functional.
If AWS deployment hits issues:

1. **Phase 1–2 issues:** Continue running locally. AWS infra idles (minimal cost).
2. **Phase 3 issues:** Kill ECS app task, run locally against local services.
3. **Phase 4 issues:** Observability is additive — disable OTLP env vars to
   fall back to stdout-only logging.

The app doesn't know where it's running. Switching between local and AWS
is an environment variable change.

---

## 9. Future Considerations (Out of Scope)

- **CI/CD:** GitHub Actions → ECR push → ECS deploy (after manual deploys are stable)
- **Market-hours scheduling:** EventBridge to start/stop ECS tasks at 9:25 ET / 16:05 ET
- **Multi-symbol scaling:** If load grows, split symbols across multiple app tasks
- **Alerting integration:** Signal → SNS → SMS/email for trade signals
- **Backup:** Automated EBS snapshots for InfluxDB data
