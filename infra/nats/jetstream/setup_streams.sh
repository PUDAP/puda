#!/bin/sh
# Apply JetStream streams and shared KV buckets declaratively.
set -eu

NATS_URL=${NATS_URL:-nats://localhost:4222}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STREAMS_DIR=${STREAMS_DIR:-$SCRIPT_DIR/streams}
REPLICAS=${REPLICAS:?REPLICAS must be set to 1 or 3}

case "$REPLICAS" in
  1|3) ;;
  *)
    echo "ERROR: REPLICAS must be 1 or 3 (got: $REPLICAS)" >&2
    exit 1
    ;;
esac

if [ ! -d "$STREAMS_DIR" ]; then
  echo "ERROR: streams directory not found: $STREAMS_DIR" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required to inject the deployment replica count" >&2
  exit 1
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

set -- "$STREAMS_DIR"/*.json
if [ ! -e "$1" ]; then
  echo "ERROR: no stream configs in $STREAMS_DIR" >&2
  exit 1
fi

echo "Connecting to NATS at $NATS_URL..."
echo "Using stream configs in $STREAMS_DIR"
echo "Applying replication factor: $REPLICAS"

for config in "$STREAMS_DIR"/*.json; do
  name=$(basename "$config" .json)
  effective_config="$TMP_DIR/$name.json"
  jq --argjson replicas "$REPLICAS" '.num_replicas = $replicas' \
    "$config" > "$effective_config"
  echo "Configuring stream '$name' from $(basename "$config")..."
  if nats stream info "$name" -s "$NATS_URL" >/dev/null 2>&1; then
    echo "  - Stream exists. Updating..."
    nats stream edit "$name" --config "$effective_config" -s "$NATS_URL" --force
  else
    echo "  - Stream missing. Creating..."
    nats stream add "$name" --config "$effective_config" -s "$NATS_URL"
  fi
  echo "$name configured."
done

for name in COMMANDS EVENTS; do
  if nats stream info "$name" -s "$NATS_URL" >/dev/null 2>&1; then
    echo "Removing obsolete stream '$name'..."
    nats stream rm "$name" -s "$NATS_URL" --force
  fi
done

for name in MACHINE_STATE MACHINE_COMMANDS LIVESTREAMS; do
  echo "Configuring KV bucket '$name' with replicas=$REPLICAS..."
  if nats kv info "$name" -s "$NATS_URL" >/dev/null 2>&1; then
    nats kv edit "$name" -s "$NATS_URL" --replicas "$REPLICAS" >/dev/null
  else
    nats kv add "$name" -s "$NATS_URL" --history 1 --replicas "$REPLICAS"
  fi
  echo "$name configured."
done

echo "All streams and KV buckets configured successfully."
