set dotenv-load := true

# TastyTrade SDK - Common development recipes
# Run `just --list` to see all available recipes

# First-time setup: install dependencies and activate pre-commit hooks
setup:
    uv sync
    git config core.hooksPath .githooks
    @echo "Setup complete. Pre-commit hooks active."

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

# Trade chains: just chains, just chains /ZB, just chains /ZB --json
chains *args:
    uv run tasty-subscription chains {{ if args =~ '^/' { "--underlying " + args } else { args } }}

# Campaign P&L: just campaign, just campaign /ZB
campaign *args:
    uv run tasty-subscription chains --campaign {{ if args =~ '^/' { "--underlying " + args } else { args } }}

# Roll history: just campaign-detail, just campaign-detail /ZB
campaign-detail *args:
    uv run tasty-subscription chains --detail {{ if args =~ '^/' { "--underlying " + args } else { args } }}

# Backfill historical account events into InfluxDB (idempotent)
backfill:
    uv run python scripts/backfill_influxdb.py

# Option chain: just options SPX, just options /GC --dte 0,30,45 --strikes
options symbol *args:
    uv run tasty-subscription options --symbol "{{symbol}}" {{args}}

# --- Charting ---

# Live chart: just chart, just chart SPY, just chart BTC/USD:CXTALP 8092
chart symbol="SPX" port="8091" interval="m":
    uv run tasty-chart --symbol "{{symbol}}" --interval {{interval}} --port {{port}}

# List running chart servers
chart-list:
    @lsof -iTCP -sTCP:LISTEN -P 2>/dev/null | grep tasty-cha | awk '{split($9,a,":"); print "  port=" a[2] "  pid=" $2}' || echo "  No chart servers running"

# Kill chart server on a port: just chart-kill 8091
chart-kill port:
    @kill $(lsof -t -i :{{port}} 2>/dev/null) 2>/dev/null && echo "Stopped chart server on :{{port}}" || echo "No process on :{{port}}"
