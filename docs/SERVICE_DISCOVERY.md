# Service Discovery & Configuration Resolution

This document describes how the application discovers infrastructure services
(Redis, InfluxDB) across different runtime environments.

## The Problem

The application runs in two environments:

| Environment | Redis | InfluxDB | Why |
|---|---|---|---|
| **Inside devcontainer** | `localhost:6379` | `localhost:8086` | `network_mode: host` shares the host's network |
| **Host machine (SSH)** | `localhost:6379` | `localhost:8086` | Port-mapped via Docker Compose |

Both environments use `localhost` because the devcontainer runs with `network_mode: host`.
The root Docker Compose services (Redis, InfluxDB, Telegraf) expose their ports on `0.0.0.0`,
making them reachable from both host processes and the devcontainer.

## The Solution: Layered Resolution

Configuration values are resolved through a three-layer precedence chain:

```
os.environ  →  Redis (.env file)  →  Code default
   (1)              (2)                  (3)
```

### Layer 1: `os.environ` (highest priority)

Set by the `env_file` directive in `.devcontainer/docker-compose.yml` (which
loads `../.env` into the container), or by `source .env` on the host. This
layer handles **application credentials** (API tokens, org names, etc.).

The devcontainer compose file (`.devcontainer/docker-compose.yml`) loads
environment variables via:

```yaml
env_file:
  - ../.env
environment:
  HOST_HOME: "${HOME}"
```

Because the container uses `network_mode: host`, no service hostname overrides
(like `REDIS_HOST: redis`) are needed — `localhost` works everywhere.

### Layer 2: Redis (populated from `.env`)

Application configuration (tokens, credentials, org names) lives in `.env`
and is loaded into Redis by `RedisConfigManager.initialize()`. During
initialization, `os.environ` values are merged on top so that Layer 1
overrides persist into Redis as well.

### Layer 3: Code defaults (lowest priority)

All service discovery defaults use **localhost** values:

- `REDIS_HOST` → `"localhost"`
- `INFLUX_DB_URL` → `"http://localhost:8086"`

These work in both environments because of `network_mode: host`.

## How It Works In Practice

### Inside the devcontainer

1. `env_file: ../.env` loads application credentials into `os.environ`
2. `network_mode: host` means `localhost:6379` reaches the host's Redis
3. `config.get("INFLUX_DB_URL")` checks `os.environ` (empty for infra) →
   checks Redis (empty) → returns code default `"http://localhost:8086"`

### On the host machine (SSH)

1. `source .env` or hook scripts load credentials into `os.environ`
2. `localhost:6379` reaches Redis directly (port-mapped by root Docker Compose)
3. Same resolution path as above — code defaults work

## Key Design Rules

### DO NOT put service hostnames in `.env`

The `.env` file is shared between host and container via volume mount.
Service discovery belongs in code defaults — never in `.env`. Only
application credentials (tokens, org names, bucket names) go in `.env`.

### DO NOT change code defaults away from `localhost`

Code defaults (`"localhost"`, `"http://localhost:8086"`) work in both
environments because of `network_mode: host`. Changing them to Docker
DNS names would break host usage.

### Devcontainer uses `network_mode: host`

The devcontainer does NOT use Docker bridge networking. It shares the
host's network stack directly. This means:
- `localhost` inside the container = `localhost` on the host
- No Docker DNS names needed (no `redis:6379` or `influxdb:8086`)
- No `environment:` overrides for service hostnames required
- Port forwarding in `devcontainer.json` is unnecessary

### Hook scripts self-source `.env`

Claude Code hooks (`.claude/hooks/stop_hook.sh`, `subagent_stop_hook.sh`)
source `.env` at the start of execution. This ensures environment variables
are available in Docker containers where `.env` values are loaded into
`os.environ` but not into the shell profile. The pattern:

```bash
if [ -f "$PWD/.env" ]; then
    set -a
    . "$PWD/.env"
    set +a
fi
```

### Rebuilding the devcontainer

If you modify `.devcontainer/docker-compose.yml` (e.g., add volumes,
change `env_file`), you must rebuild the devcontainer for changes to
take effect. The `.env` file itself is read at runtime via volume mount
and does NOT require a rebuild when changed.

## Files Involved

| File | Role |
|---|---|
| `.devcontainer/docker-compose.yml` | Devcontainer config: `network_mode: host`, `env_file: ../.env` |
| `.env` | Application config (tokens, credentials) — no service hosts |
| `src/tastytrade/config/manager.py` | `config.get()` implements the 3-layer resolution |
| `src/tastytrade/messaging/processors/redis.py` | Redis pubsub — `os.environ` + localhost default |
| `src/tastytrade/messaging/processors/influxdb.py` | InfluxDB writer — localhost default |
| `src/tastytrade/connections/subscription.py` | Subscription store — `os.environ` + localhost default |
| `src/tastytrade/subscription/status.py` | Status query — `os.environ` + localhost default |

## Adding a New Infrastructure Service

If you add a new service (e.g., Kafka, PostgreSQL):

1. Add the service to `docker-compose.yml` (root) with port mapping on `0.0.0.0`
2. Use `os.environ.get("KAFKA_HOST", "localhost")` in the Python code
3. Do NOT add `KAFKA_HOST` to `.env`
4. No devcontainer changes needed — `network_mode: host` means `localhost` works
