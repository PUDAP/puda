"""NATS JetStream names and command timeouts shared across the SDK.

Keep in sync with infra/nats/streams/*.json (declarative JetStream source of truth).
"""

NAMESPACE = "puda"

# PUDA Edge Protocol version this SDK speaks (MAJOR.MINOR), sent in every pong.
# Clients judge an edge by this, not by SDK package version: a minor bump only
# adds; a new major is breaking.
PROTOCOL_VERSION = "1.0"
STREAM_COMMAND_QUEUE = "COMMAND_QUEUE"
STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"

# Shared JetStream KV buckets. Key = machine_id (not one bucket per machine).
KV_BUCKET_STATE = "MACHINE_STATE"
KV_BUCKET_COMMANDS = "MACHINE_COMMANDS"

QUEUE_COMMAND_TIMEOUT = 120
IMMEDIATE_COMMAND_TIMEOUT = 10  # seconds a client waits for an immediate reply
