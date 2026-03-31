#!/bin/sh
# Auto-register the Redis database with RedisInsight on first startup.
# Runs as the container entrypoint, waits for the RedisInsight API to be ready,
# adds the database if not already present, then keeps the container alive.

# Start RedisInsight in the background (working dir is /usr/src/app)
node redisinsight/api/dist/src/main &
RI_PID=$!

# Wait for the API to become available
echo "Waiting for RedisInsight API..."
until wget -q -O- http://0.0.0.0:5540/api/databases > /dev/null 2>&1; do
  sleep 1
done

# Add Redis database if none are configured yet
EXISTING=$(wget -q -O- http://0.0.0.0:5540/api/databases 2>/dev/null)
if [ "$EXISTING" = "[]" ]; then
  wget -q -O- --header="Content-Type: application/json" \
    --post-data='{"name":"local","host":"redis","port":6379}' \
    http://0.0.0.0:5540/api/databases > /dev/null 2>&1
  echo "Redis database auto-registered."
else
  echo "Database already configured, skipping."
fi

# Keep the container running with the RedisInsight process
wait $RI_PID
