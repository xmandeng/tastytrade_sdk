# Test Coverage Strategy

> **Jira:** [TT-125](https://mandeng.atlassian.net/browse/TT-125)
> **Baseline:** 63% (7100 statements) — measured 2026-04-07
> **After dead code removal:** 63% (6936 statements, 164 dead statements removed)

## Principles

1. **Cover the right code, not an arbitrary percentage.** 80% of the wrong code is worse than 60% of critical paths.
2. **Dead code is negative coverage.** It inflates the denominator. Remove it first.
3. **Exclusions must be justified and documented.** Every `# pragma: no cover` needs a reason.
4. **Inbound models don't need behavioral tests.** Pydantic `extra="allow"` models are data containers — test the logic that uses them, not the fields.

---

## Module Categories

### Tier 1: Business Logic — Target 95%+

Pure functions and classes with no I/O dependencies. These are the most valuable to test and the easiest to cover.

| Module | Current | Statements | Notes |
|--------|---------|------------|-------|
| `analytics/engines/hull_macd.py` | 96% | 157 | Near target |
| `analytics/strategies/patterns.py` | 89% | 365 | Pattern matching logic |
| `analytics/strategies/models.py` | 88% | 217 | Strategy data models |
| `analytics/strategies/health.py` | 96% | 75 | Health monitoring |
| `analytics/strategies/classifier.py` | 100% | 66 | Complete |
| `analytics/metrics.py` | 100% | 110 | Complete |
| `analytics/positions.py` | 64% | 375 | **Priority** — position analytics |
| `backtest/replay.py` | 93% | 73 | Near target |
| `backtest/runner.py` | 100% | 31 | Complete |
| `market/option_chains.py` | 98% | 66 | Near target |
| `market/instruments.py` | 86% | 72 | Near target |
| `messaging/handlers.py` | 74% | 177 | Event routing logic |
| `subscription/resolver.py` | 87% | 89 | Position → subscription resolution |
| `subscription/status.py` | 84% | 117 | Connection status tracking |
| `accounts/transactions.py` | 82% | 125 | Transaction processing |
| `utils/validators.py` | 56% | 34 | **Priority** — pure validation |
| `utils/helpers.py` | 45% | 11 | Small — easy win |
| `utils/time_series.py` | 36% | 87 | **Priority** — data transforms |

### Tier 2: Integration/Infrastructure — Target 70%+

I/O-dependent code (Redis, WebSocket, HTTP). Test the decision logic via mocks; exclude raw transport.

| Module | Current | Statements | Notes |
|--------|---------|------------|-------|
| `accounts/orchestrator.py` | 76% | 417 | Reconnection/retry logic testable |
| `accounts/streamer.py` | 58% | 217 | WebSocket lifecycle |
| `accounts/publisher.py` | 60% | 90 | Redis publishing |
| `connections/auth.py` | 93% | 91 | Near target |
| `connections/requests.py` | 48% | 96 | HTTP client wrapper |
| `connections/sockets.py` | 31% | 255 | WebSocket + DXLink protocol |
| `connections/routing.py` | 36% | 53 | Message routing |
| `connections/subscription.py` | 43% | 105 | Redis subscription management |
| `subscription/orchestrator.py` | 33% | 273 | Main subscription loop |
| `providers/subscriptions.py` | 51% | 126 | Redis pub/sub data feed |
| `providers/market.py` | 63% | 100 | InfluxDB + market data |
| `messaging/models/messages.py` | 69% | 132 | DXLink message models |
| `messaging/processors/redis.py` | 78% | 27 | Near target |
| `messaging/processors/influxdb.py` | 33% | 39 | InfluxDB writer |
| `config/manager.py` | 49% | 204 | Env/Redis config resolution |
| `common/exceptions.py` | 72% | 69 | Exception classes |

### Tier 3: Justified Exclusions — `# pragma: no cover`

Code that **should not** be unit-tested because it requires a live runtime environment, is purely presentation, or is a thin CLI wrapper.

| Module | Statements | Reason |
|--------|------------|--------|
| `charting/server.py` | 209 | FastAPI + WebSocket live server — requires browser |
| `charting/feed.py` | 43 | Live market data feed for charting |
| `charting/indicators.py` | 124 | Chart indicator rendering |
| `charting/cli.py` | 20 | Thin CLI wrapper over `ChartServer` |
| `subscription/cli.py` | 299 | Click CLI — tests live Redis/WebSocket services |
| `signal/cli.py` | 66 | Click CLI — tests live market connections |
| `backtest/cli.py` | 91 | Click CLI — tests live InfluxDB |
| `analytics/visualizations/plots.py` | 157 | Plotly chart rendering |
| `analytics/indicators/momentum.py` | 76 | Technical indicator computation (InfluxDB-dependent) |
| `common/observability.py` | 99 | OpenTelemetry + Grafana Cloud setup |
| `common/logging.py` | 24 | File/console logging setup |

**Total excluded: ~1,208 statements** (17% of codebase)

### Exclusion justifications

- **CLI modules** (`subscription/cli.py`, `signal/cli.py`, `backtest/cli.py`, `charting/cli.py`): These are Click entrypoints that bootstrap live connections to Redis, WebSocket, and InfluxDB. Testing via `CliRunner` would require mocking the entire runtime. The orchestrators and business logic they call are tested independently.

- **Charting server** (`charting/server.py`, `feed.py`, `indicators.py`): FastAPI server with WebSocket endpoints serving live chart data. Requires a running browser + market data feed. Validated via manual functional testing.

- **Visualization** (`analytics/visualizations/plots.py`): Plotly figure construction. Output is visual — automated assertions on figure traces are brittle and low-value. Validated by visual inspection during signal development.

- **Observability** (`common/observability.py`, `common/logging.py`): OpenTelemetry and logging setup. These configure third-party infrastructure; the setup code itself doesn't contain business logic. Validated by observing logs in Grafana Cloud.

- **Momentum indicators** (`analytics/indicators/momentum.py`): Depends on InfluxDB for historical data retrieval. The computation logic is thin; the InfluxDB queries dominate.

---

## Coverage Configuration

Coverage is configured in `pyproject.toml` under `[tool.coverage.*]` sections.

### Pragma Guide

Use `# pragma: no cover` sparingly, always with a reason:

```python
# Justified patterns:
if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()

except ConnectionError:  # pragma: no cover - requires live service
    logger.error("Connection lost")

def start_server():  # pragma: no cover - requires runtime environment
    uvicorn.run(app, port=8080)
```

**Never use pragma for:**
- Business logic branches
- Error handling in pure functions
- Model validation
- Anything testable with mocks

---

## Dead Code Tooling

### Vulture

Vulture is configured as a dev dependency. Run it to detect unused code:

```bash
uv run vulture src/tastytrade/ --min-confidence 80
```

A whitelist file (`vulture_whitelist.py`) documents false positives:
- Pydantic `@field_validator` / `@model_validator` methods
- Click `@cli.command()` decorated functions
- `__aexit__` protocol parameters
- Pydantic `model_config` class variables

### Maintenance

- Run vulture before each PR that adds/removes code
- Dead code should be removed, not commented out
- If vulture flags something as dead that's actually used dynamically, add it to the whitelist with a comment explaining why
