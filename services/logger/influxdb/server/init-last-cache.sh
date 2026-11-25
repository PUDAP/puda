#!/bin/sh
# Create a last-value cache on telemetry keyed by machine_id once that table exists.
# Grafana: SELECT * FROM last_cache('telemetry', 'telemetry_last')
set -eu

HOST="${INFLUXDB3_HOST_URL:-http://influxdb:8181}"
TOKEN="${INFLUXDB_TOKEN:?INFLUXDB_TOKEN is required}"
DB="${INFLUXDB_DATABASE:-puda}"
CACHE_NAME="${INFLUXDB_LAST_CACHE_NAME:-telemetry_last}"
TTL="${INFLUXDB_LAST_CACHE_TTL:-10min}"

export INFLUXDB3_AUTH_TOKEN="$TOKEN"
export INFLUXDB3_HOST_URL="$HOST"

echo "Waiting for InfluxDB at $HOST"

i=0
while [ "$i" -lt 60 ]; do
  if influxdb3 ping --host "$HOST" >/dev/null 2>&1; then
    break
  fi
  # ping may not exist on 3.9; HTTP health is enough
  if command -v curl >/dev/null 2>&1; then
    curl -sf "$HOST/health" >/dev/null && break || true
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import urllib.request; urllib.request.urlopen('$HOST/health', timeout=2)" 2>/dev/null && break || true
  fi
  i=$((i + 1))
  sleep 2
done

echo "Ensuring database $DB exists"
influxdb3 create database "$DB" --host "$HOST" --token "$TOKEN" 2>/dev/null || true

echo "Waiting for table telemetry in $DB (first logger health write)"
i=0
while [ "$i" -lt 180 ]; do
  tables=$(influxdb3 query --host "$HOST" --token "$TOKEN" --database "$DB" \
    "SHOW TABLES" 2>/dev/null || true)
  echo "$tables" | grep -q telemetry && break
  i=$((i + 1))
  sleep 10
done

if ! echo "${tables:-}" | grep -q telemetry; then
  echo "telemetry table not found yet; start the logger and re-run this service" >&2
  exit 1
fi

echo "Creating last-value cache $CACHE_NAME on $DB.telemetry (key=machine_id, ttl=$TTL)"
if influxdb3 create last_cache \
  --host "$HOST" \
  --token "$TOKEN" \
  --database "$DB" \
  --table telemetry \
  --key-columns machine_id \
  --count 1 \
  --ttl "$TTL" \
  "$CACHE_NAME"
then
  echo "Last-value cache $CACHE_NAME ready"
  exit 0
fi

# Already exists is success (idempotent re-runs).
echo "create last_cache returned non-zero; assuming it already exists"
exit 0
