# Market Data Subscription CLI (`tasty-subscription`)

The `tasty-subscription` CLI manages market data subscriptions including historical backfill, live streaming, and operational monitoring.

---

## Commands

### `run` — Start subscription with historical backfill and live streaming

```bash
uv run tasty-subscription run \
  --start-date 2026-01-15 \
  --symbols AAPL,SPY,QQQ \
  --intervals 1d,1h,5m \
  --log-level INFO
```

### `status` — Query active subscriptions

```bash
uv run tasty-subscription status
uv run tasty-subscription status --json
```

---

## Run Command Options

| Option | Required | Description |
|--------|----------|-------------|
| `--start-date` | Yes | Historical backfill start date (YYYY-MM-DD) |
| `--symbols` | Yes | Comma-separated symbols (e.g., `AAPL,SPY,QQQ`) |
| `--intervals` | Yes | Comma-separated intervals: `1d`, `1h`, `30m`, `15m`, `5m`, `m` |
| `--log-level` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`) |
| `--health-interval` | No | Seconds between health logs (default: `300`) |

---

## Full Production Example

```bash
uv run tasty-subscription run \
  --start-date 2026-01-20 \
  --symbols BTC/USD:CXTALP,NVDA,AAPL,QQQ,SPY,SPX \
  --intervals 1d,1h,30m,15m,5m,m \
  --log-level INFO
```

**Expected Output:**

```
TastyTrade Market Data Subscription - Starting
Configuration:
  Start Date:  2026-01-20
  Symbols:     BTC/USD:CXTALP, NVDA, AAPL, QQQ, SPY, SPX
  Intervals:   1d, 1h, 30m, 15m, 5m, m
  Feed Count:  36 candle feeds
Subscribing to ticker feeds for 6 symbols
Subscribing to 36 candle feeds from 2026-01-20
Subscription and back-fill complete for 36/36 subscriptions
Subscription active - press Ctrl+C to stop
Health — Uptime: 5m | 6 channels active
```

---

## Graceful Shutdown

Press `Ctrl+C` for clean shutdown (flushes data, closes connections).
