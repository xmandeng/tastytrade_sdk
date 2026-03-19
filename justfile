set dotenv-load := true

# TastyTrade SDK - Common development recipes
# Run `just --list` to see all available recipes

# Default symbols and intervals for subscription
default_symbols := "BTC/USD:CXTALP,NVDA,AAPL,QQQ,SPY,SPX"
default_intervals := "1d,1h,30m,15m,5m,m"

# Prior workday calculation: Mon->Fri(-3), Sun->Fri(-2), else->yesterday(-1)
# All date calculations use Eastern Time (America/New_York)
prior_workday := `TZ='America/New_York' date -d "-$(case $(TZ='America/New_York' date +%u) in 1) echo 3;; 7) echo 2;; *) echo 1;; esac) days" +%Y-%m-%d`

# Check status of active subscriptions
status:
    uv run tasty-subscription status

# Check status in JSON format
status-json:
    uv run tasty-subscription status --json

# Run subscription with defaults (start date = prior workday)
subscribe start_date=prior_workday log_level="INFO":
    uv run tasty-subscription run \
        --symbols "{{default_symbols}}" \
        --intervals {{default_intervals}} \
        --start-date {{start_date}} \
        --log-level {{log_level}}

# Run subscription with custom symbols and intervals
subscribe-custom symbols intervals start_date=prior_workday log_level="INFO":
    uv run tasty-subscription run \
        --symbols "{{symbols}}" \
        --intervals {{intervals}} \
        --start-date {{start_date}} \
        --log-level {{log_level}}

# Run account stream (positions/balances to Redis)
account-stream log_level="INFO":
    uv run tasty-subscription account-stream \
        --log-level {{log_level}}

# Show current position metrics from Redis
positions:
    uv run tasty-subscription positions

# Aggregated position summary by underlying (pre-calculated)
positions-summary:
    uv run tasty-subscription positions-summary

# Deterministic strategy classification (no LLM)
strategies:
    uv run tasty-subscription strategies

# Strategy classification in JSON format
strategies-json:
    uv run tasty-subscription strategies --json

# Trade chain lifecycle summary (rolls, P&L, fees)
chains:
    uv run tasty-subscription chains

# Trade chain lifecycle summary in JSON format
chains-json:
    uv run tasty-subscription chains --json

# Backfill historical account events into InfluxDB (idempotent)
backfill:
    uv run python scripts/backfill_influxdb.py

# Position summary with LLM strategy identification (legacy)
positions-strategies:
    uv run tasty-subscription positions-summary | claude --print \
        "Identify the strategy for each underlying. Output ONLY a markdown table \
        with columns: Underlying, Strategy, Net Delta, Num Legs. No reasoning or notes. \
        Strategy reference: short strangle (2 short options, no stock), \
        iron condor (short strangle + protective wings), \
        covered call (long stock + short call), \
        jade lizard (short OTM vertical spread + short option on opposite side), \
        covered jade lizard (long stock + jade lizard overlay)."
