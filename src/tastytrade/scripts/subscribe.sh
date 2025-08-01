#!/bin/bash

# Define symbols and intervals
SYMBOLS=("SPY" "AAPL" "SPX" "QQQ" "NVDA" "BTC/USD:CXTALP")
INTERVALS=("1m" "5m" "15m" "30m" "1h" "1d")

# Base URL
BASE_URL="http://127.0.0.1:8000"

# Subscribe to feed for all symbols
echo "Subscribing to feed for all symbols..."
curl -X POST "${BASE_URL}/subscribe/feed" \
  -H "Content-Type: application/json" \
  -d "{\"symbols\": [\"${SYMBOLS[0]}\", \"${SYMBOLS[1]}\", \"${SYMBOLS[2]}\", \"${SYMBOLS[3]}\", \"${SYMBOLS[4]}\", \"${SYMBOLS[5]}\"]}"

# Subscribe to candles for each symbol and interval
echo "Subscribing to candles for each symbol and interval..."
for symbol in "${SYMBOLS[@]}"; do
  for interval in "${INTERVALS[@]}"; do
    echo "Subscribing to ${symbol} with interval ${interval}..."
    curl -X POST "${BASE_URL}/subscribe/candles" \
      -H "Content-Type: application/json" \
      -d "{\"symbol\": \"${symbol}\", \"interval\": \"${interval}\"}"
    # Small delay to prevent overwhelming the server
    sleep 0.2
  done
done

echo "All subscriptions completed."
