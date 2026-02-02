# TastyTrade SDK - Common development recipes
# Run `just --list` to see all available recipes

# Default symbols and intervals for subscription
default_symbols := "BTC/USD:CXTALP,NVDA,AAPL,QQQ,SPY,SPX"
default_intervals := "1d,1h,30m,15m,5m,m"

# Check status of active subscriptions
status:
    uv run tasty-subscription status

# Check status in JSON format
status-json:
    uv run tasty-subscription status --json

# Run subscription with defaults (start date = today)
subscribe start_date=`date +%Y-%m-%d` log_level="INFO":
    uv run tasty-subscription run \
        --symbols "{{default_symbols}}" \
        --intervals {{default_intervals}} \
        --start-date {{start_date}} \
        --log-level {{log_level}}

# Run subscription with custom symbols and intervals
subscribe-custom symbols intervals start_date=`date +%Y-%m-%d` log_level="INFO":
    uv run tasty-subscription run \
        --symbols "{{symbols}}" \
        --intervals {{intervals}} \
        --start-date {{start_date}} \
        --log-level {{log_level}}
