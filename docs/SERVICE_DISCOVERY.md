# Service Discovery & Configuration Resolution

This document describes how the application discovers infrastructure services
(Redis, InfluxDB) across different runtime environments.

## The Problem

The application runs in two environments with different networking:

| Environment | Redis | InfluxDB | Why |
|---|---|---|---|
| **Inside devcontainer** | `redis:6379` | `influxdb:8086` | Docker DNS on bridge network |
| **Host machine** | `localhost:6379` | `localhost:8086` | Port-mapped via Docker Compose |

The `.env` file is volume-mounted into the container (`..:/workspace:cached`),
so it is shared between both environments. Putting service hostnames in `.env`
would immediately affect both environments — there is no way to set a value
that works for both.

## The Solution: Layered Resolution

Configuration values are resolved through a three-layer precedence chain:

```
os.environ  →  Redis (.env file)  →  Code default
   (1)              (2)                  (3)
```

### Layer 1: `os.environ` (highest priority)

Set by Docker Compose `environment` section inside the container, or by
`source .env` on the host. This layer handles **infrastructure overrides**
that differ between environments.

The devcontainer compose file (`.devcontainer/docker-compose.yml`) sets:

```yaml
environment:
  REDIS_HOST: redis
  INFLUX_DB_URL: http://influxdb:8086
```

These override any values from `env_file` and are baked into `os.environ`
at container creation time.

### Layer 2: Redis (populated from `.env`)

Application configuration (tokens, credentials, org names) lives in `.env`
and is loaded into Redis by `RedisConfigManager.initialize()`. During
initialization, `os.environ` values are merged on top so that Layer 1
overrides persist into Redis as well.

### Layer 3: Code defaults (lowest priority)

All service discovery defaults use **host-friendly** values:

- `REDIS_HOST` → `"localhost"`
- `INFLUX_DB_URL` → `"http://localhost:8086"`

These ensure the application works on the host machine with zero
configuration. Inside the container, Layer 1 overrides them.

## How It Works In Practice

### Inside the devcontainer

1. Docker Compose sets `os.environ["REDIS_HOST"] = "redis"` and
   `os.environ["INFLUX_DB_URL"] = "http://influxdb:8086"`
2. `config.get("INFLUX_DB_URL")` checks `os.environ` first → returns
   `"http://influxdb:8086"`
3. Redis bootstrap reads `os.environ["REDIS_HOST"]` → connects to `redis:6379`

### On the host machine

1. `os.environ` has no `REDIS_HOST` or `INFLUX_DB_URL`
2. `config.get("INFLUX_DB_URL")` checks `os.environ` (empty) → checks
   Redis (empty) → returns code default `"http://localhost:8086"`
3. Redis bootstrap falls through to code default → connects to
   `localhost:6379`

## Key Design Rules

### DO NOT put service hostnames in `.env`

The `.env` file is shared between host and container via volume mount.
Adding `REDIS_HOST=localhost` would break the container (where Docker DNS
names are needed). Adding `REDIS_HOST=redis` would break the host.

Service discovery belongs in `os.environ` (set by the runtime) and code
defaults — never in `.env`.

### DO NOT change code defaults to Docker DNS names

Code defaults (`"localhost"`, `"http://localhost:8086"`) must remain
host-friendly. The container override is handled by Docker Compose's
`environment` section, which sets `os.environ`.

If code defaults are changed to `"redis"` or `"http://influxdb:8086"`, the
host environment will fail because Docker DNS names don't resolve outside
the container network.

### DO NOT remove the compose `environment` section

The `environment` block in `.devcontainer/docker-compose.yml` is the
mechanism that makes the container work. Without it, the code defaults
(`localhost`) would be used inside the container, failing to reach services
on the Docker bridge network.

### Rebuilding the devcontainer

Docker Compose `environment` values are set at container creation time.
If you modify the `environment` section, you must rebuild the devcontainer
for changes to take effect. Unlike `.env` (which is read at runtime via
volume mount), compose environment changes require a restart.

## Files Involved

| File | Role |
|---|---|
| `.devcontainer/docker-compose.yml` | Sets `os.environ` overrides for container |
| `.env` | Application config (tokens, credentials) — no service hosts |
| `src/tastytrade/config/manager.py` | `config.get()` implements the 3-layer resolution |
| `src/tastytrade/messaging/processors/redis.py` | Redis pubsub — `os.environ` + localhost default |
| `src/tastytrade/messaging/processors/influxdb.py` | InfluxDB writer — localhost default |
| `src/tastytrade/connections/subscription.py` | Subscription store — `os.environ` + localhost default |
| `src/tastytrade/subscription/status.py` | Status query — `os.environ` + localhost default |

## Adding a New Infrastructure Service

If you add a new service (e.g., Kafka, PostgreSQL):

1. Add the service to `docker-compose.yml` (root) on the `internal_net` network
2. Add a compose `environment` override in `.devcontainer/docker-compose.yml`
   with the Docker DNS name (e.g., `KAFKA_HOST: kafka`)
3. Use `os.environ.get("KAFKA_HOST", "localhost")` in the Python code
4. Do NOT add `KAFKA_HOST` to `.env`
