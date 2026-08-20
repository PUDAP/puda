"""NATS JetStream names shared across the SDK.

Keep in sync with infra/nats/streams/*.json (declarative JetStream source of truth).
"""

NAMESPACE = "puda"
STREAM_COMMAND_QUEUE = "COMMAND_QUEUE"
STREAM_COMMAND_IMMEDIATE = "COMMAND_IMMEDIATE"
STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"
