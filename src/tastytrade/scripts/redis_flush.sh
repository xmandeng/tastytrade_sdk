#!/bin/bash

# sudo apt-get install -y redis-tools

# Flush Redis cache on remote host
echo "Flushing Redis cache..."
redis-cli -h ${REDIS_HOST:-localhost} -p ${REDIS_PORT:-6379} FLUSHALL
echo "Redis cache flushed successfully."
