#!/bin/bash
# Apply JetStream streams from streams/*.json (single declarative source of truth).
#
# Must stay aligned with:
#   - libs/python-sdk EdgeNatsClient / CommandService (lowercase puda.* subjects)
#   - apps/cli ResponseDispatcher (RESPONSE_QUEUE / RESPONSE_IMMEDIATE)
#
# Events and telemetry use core NATS only — do not add JetStream streams for them.
set -euo pipefail

NATS_URL=${NATS_URL:-"nats://localhost:4222"}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STREAMS_DIR="${STREAMS_DIR:-$SCRIPT_DIR/streams}"

# Legacy streams from an older setup (uppercase PUDA.* / COMMANDS+EVENTS).
# Safe to remove: they never matched SDK subjects and would only hold dead traffic.
OBSOLETE_STREAMS=(COMMANDS EVENTS)

# Shared KV buckets (key = machine_id). Edges also create these on connect if missing.
KV_BUCKETS=(MACHINE_STATE MACHINE_COMMANDS)

if [[ ! -d "$STREAMS_DIR" ]]; then
  echo "ERROR: streams directory not found: $STREAMS_DIR" >&2
  exit 1
fi

shopt -s nullglob
STREAM_CONFIGS=("$STREAMS_DIR"/*.json)
if [[ ${#STREAM_CONFIGS[@]} -eq 0 ]]; then
  echo "ERROR: no stream configs in $STREAMS_DIR" >&2
  exit 1
fi

echo "Connecting to NATS at $NATS_URL..."
echo "Using stream configs in $STREAMS_DIR"

ensure_stream() {
  local CONFIG=$1
  local NAME
  NAME="$(basename "$CONFIG" .json)"

  echo "Configuring stream '$NAME' from $(basename "$CONFIG")..."
  if nats stream info "$NAME" -s "$NATS_URL" >/dev/null 2>&1; then
    echo "  - Stream exists. Updating..."
    nats stream edit --config "$CONFIG" -s "$NATS_URL" --force
  else
    echo "  - Stream missing. Creating..."
    nats stream add --config "$CONFIG" -s "$NATS_URL"
  fi
  echo "✅ $NAME configured."
}

remove_obsolete_stream() {
  local NAME=$1
  if nats stream info "$NAME" -s "$NATS_URL" >/dev/null 2>&1; then
    echo "Removing obsolete stream '$NAME' (wrong subjects / superseded)..."
    nats stream rm "$NAME" -s "$NATS_URL" --force
    echo "✅ $NAME removed."
  fi
}

for config in "${STREAM_CONFIGS[@]}"; do
  ensure_stream "$config"
done

for name in "${OBSOLETE_STREAMS[@]}"; do
  remove_obsolete_stream "$name"
done

ensure_kv_bucket() {
  local NAME=$1
  echo "Configuring KV bucket '$NAME'..."
  if nats kv info "$NAME" -s "$NATS_URL" >/dev/null 2>&1; then
    echo "  - Bucket exists."
  else
    echo "  - Bucket missing. Creating..."
    nats kv add "$NAME" -s "$NATS_URL" --history 1
  fi
  echo "✅ $NAME configured."
}

for bucket in "${KV_BUCKETS[@]}"; do
  ensure_kv_bucket "$bucket"
done

echo "🎉 All streams and KV buckets setup successfully."
