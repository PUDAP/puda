#!/bin/bash
set -e

# Configuration
NATS_URL=${NATS_URL:-"nats://localhost:4222"}

echo "Connecting to NATS at $NATS_URL..."

# Function to create or update a stream
# Usage: ensure_stream NAME "FLAGS"
ensure_stream() {
    local NAME=$1
    local FLAGS=$2

    echo "Configuring stream '$NAME'..."

    # Try to get stream info.
    # If it fails (exit code 1), the stream doesn't exist -> Create it (add).
    # If it succeeds (exit code 0), the stream exists -> Update it (edit).
    if nats stream info "$NAME" -s "$NATS_URL" > /dev/null 2>&1; then
        echo "  - Stream exists. Updating..."
        # We use 'eval' to properly expand the quoted string of flags
        eval nats stream edit "$NAME" $FLAGS -s "$NATS_URL" --force
    else
        echo "  - Stream missing. Creating..."
        eval nats stream add "$NAME" $FLAGS -s "$NATS_URL"
    fi
    echo "✅ $NAME configured."
}

# 1. COMMANDS Stream (Work Queue)
# Handles: PUDA.*.cmd.>
# Retention: WorkQueue (deleted when processed)
CMD_FLAGS='--subjects "PUDA.*.cmd.>" \
--retention work \
--discard new \
--max-msgs-per-subject 100 \
--storage file \
--description "Global Job Queue for all PUDA machines"'

ensure_stream "COMMANDS" "$CMD_FLAGS"


# 2. EVENTS Stream (Logs/History)
# Handles: PUDA.*.evt.>, PUDA.*.cmd.response
# Retention: Limits (7 days)
EVT_FLAGS='--subjects "PUDA.*.evt.>" \
--subjects "PUDA.*.cmd.response" \
--retention limits \
--max-age 7d \
--storage file \
--description "Central Event Log for all PUDA machines"'

ensure_stream "EVENTS" "$EVT_FLAGS"

echo "🎉 All streams setup successfully."
