# Market Data & Account CLI (`tasty-subscription`)

The `tasty-subscription` CLI manages market data subscriptions, account streaming, position analytics, and strategy classification.

---

## Commands

### `run` -- Start subscription with historical backfill and live streaming

```bash
uv run tasty-subscription run \
  --start-date 2026-01-15 \
  --symbols AAPL,SPY,QQQ \
  --intervals 1d,1h,5m \
  --log-level INFO
```

| Option | Required | Description |
|--------|----------|-------------|
| `--start-date` | Yes | Historical backfill start date (YYYY-MM-DD) |
| `--symbols` | Yes | Comma-separated symbols (e.g., `AAPL,SPY,QQQ`) |
| `--intervals` | Yes | Comma-separated intervals: `1d`, `1h`, `30m`, `15m`, `5m`, `m` |
| `--log-level` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`) |
| `--health-interval` | No | Seconds between health logs (default: `300`) |

### `status` -- Query active subscriptions

```bash
uv run tasty-subscription status
uv run tasty-subscription status --json
```

### `account-stream` -- Stream account data to Redis

Streams positions, balances, and orders from the TastyTrade Account Streamer WebSocket to Redis.

```bash
uv run tasty-subscription account-stream
uv run tasty-subscription account-stream --log-level DEBUG
```

| Option | Required | Description |
|--------|----------|-------------|
| `--log-level` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`) |
| `--health-interval` | No | Seconds between health logs (default: `300`) |

### `positions` -- Show current position metrics

Reads position and market data from Redis and displays current position metrics.

```bash
uv run tasty-subscription positions
```

### `positions-summary` -- Aggregated position summary

Shows positions aggregated by underlying symbol with net delta and leg count.

```bash
uv run tasty-subscription positions-summary
```

### `strategies` -- Deterministic strategy classification

Classifies positions into recognized option strategies (iron condors, strangles, jade lizards, etc.) using a deterministic pattern matcher.

```bash
uv run tasty-subscription strategies
uv run tasty-subscription strategies --json
```

---

## Full Production Example

```bash
uv run tasty-subscription run \
  --start-date 2026-01-20 \
  --symbols BTC/USD:CXTALP,NVDA,AAPL,QQQ,SPY,SPX \
  --intervals 1d,1h,30m,15m,5m,m \
  --log-level INFO
```

---

## Graceful Shutdown

Press `Ctrl+C` for clean shutdown (flushes data, closes connections).
