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

nats_cmd() {
  if [ -n "${NATS_CA:-}" ]; then
    nats -s "$NATS_URL" --tlsca "$NATS_CA" "$@"
  else
    nats -s "$NATS_URL" "$@"
  fi
}

for config in "$STREAMS_DIR"/*.json; do
  name=$(basename "$config" .json)
  effective_config="$TMP_DIR/$name.json"
  jq --argjson replicas "$REPLICAS" '.num_replicas = $replicas' \
    "$config" > "$effective_config"
  echo "Configuring stream '$name' from $(basename "$config")..."
  if nats_cmd stream info "$name" >/dev/null 2>&1; then
    echo "  - Stream exists. Updating..."
    nats_cmd stream edit "$name" --config "$effective_config" --force
  else
    echo "  - Stream missing. Creating..."
    nats_cmd stream add "$name" --config "$effective_config"
  fi
  echo "$name configured."
done

for name in COMMANDS EVENTS; do
  if nats_cmd stream info "$name" >/dev/null 2>&1; then
    echo "Removing obsolete stream '$name'..."
    nats_cmd stream rm "$name" --force
  fi
done

for name in MACHINE_STATE MACHINE_COMMANDS LIVESTREAMS E2E_KEYRING E2E_KEYFILES; do
  echo "Configuring KV bucket '$name' with replicas=$REPLICAS..."
  if nats_cmd kv info "$name" >/dev/null 2>&1; then
    nats_cmd kv edit "$name" --replicas "$REPLICAS" >/dev/null
  else
    nats_cmd kv add "$name" --history 1 --replicas "$REPLICAS"
  fi
  echo "$name configured."
done

echo "All streams and KV buckets configured successfully."
