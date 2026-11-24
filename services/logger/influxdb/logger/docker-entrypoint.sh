#!/bin/sh
set -eu

# Validate both plaintext and E2EE settings before starting Telegraf.
/opt/puda/bin/python /opt/puda/subscriber.py --check-config

export INFLUXDB_URL="${INFLUXDB_URL:-http://localhost:8181}"
export INFLUXDB_TOKEN="${INFLUXDB_TOKEN:-token}"
export INFLUXDB_DATABASE="${INFLUXDB_DATABASE:-puda}"
export INFLUXDB_ORGANIZATION="${INFLUXDB_ORGANIZATION:-bears}"

envsubst '${INFLUXDB_URL} ${INFLUXDB_TOKEN} ${INFLUXDB_DATABASE} ${INFLUXDB_ORGANIZATION}' \
  < /etc/telegraf/telegraf.conf.template \
  > /etc/telegraf/telegraf.conf

exec telegraf --config /etc/telegraf/telegraf.conf
