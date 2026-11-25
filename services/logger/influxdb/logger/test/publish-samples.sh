#!/bin/sh
# Use only against a test broker; this publishes command requests.
set -eu
cd "$(dirname "$0")/.."
export NATS_SERVERS="${NATS_SERVERS:-nats://localhost:4222}"
exec uv run python test/publish_samples.py
