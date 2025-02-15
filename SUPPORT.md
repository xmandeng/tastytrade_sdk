
# InfluxDB Cleanup Steps

This procedure outlines the critical steps for cleaning up the InfluxDB database via CLI.

1. First, access the InfluxDB container's shell:
   ```bash
   docker exec -it influxdb bash
   ```

2. Create and configure the InfluxDB connection:
   ```bash
   influx config create \
     --config-name main-config \
     --host-url http://localhost:8086 \
     --org ${DOCKER_INFLUXDB_INIT_ORG} \
     --token ${DOCKER_INFLUXDB_INIT_ADMIN_TOKEN} \
     --active
   ```

3. Delete all CandleEvent measurements from the beginning of time until now:
   ```bash
   influx delete --bucket tastytrade \
     --start 1970-01-01T00:00:00Z \
     --stop $(date +"%Y-%m-%dT%H:%M:%SZ") \
     --predicate '_measurement="CandleEvent"'
   ```

Note: This operation permanently removes all CandleEvent measurements from the tastytrade bucket. Make sure you have necessary backups before proceeding.
