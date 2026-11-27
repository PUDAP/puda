# postgres-logger

Listens to NATS response streams and logs all command responses to PostgreSQL.

Requires PUDA Edge Protocol 1.0 (puda SDK 0.1.0rc1+, CLI 0.2.0-rc1+). Messages without a
supported `header.protocol_version` (major `1`) are rejected and not stored.

## Overview

The logger subscribes to:
- `puda.*.cmd.response.queue`
- `puda.*.cmd.response.immediate`

It extracts response data and stores them in PostgreSQL:
- `command_log`: Stores all command responses received from machines, including `header.protocol_version`

Note: The service only listens to response streams (`{namespace}.*.cmd.response.*`), not command streams. It never subscribes to `puda.*.cmd.immediate`, `cmd.ping` or `update` subjects; immediate commands are recorded from `RESPONSE_IMMEDIATE`.

The `RESPONSE_QUEUE` and `RESPONSE_IMMEDIATE` streams belong to the provisioner (`infra/nats/jetstream/setup_streams.sh`). The logger only checks them (`STREAM.INFO`) and never creates, updates or deletes a stream; startup fails if one is missing. It uses one durable consumer per stream (`logger_resp_queue`, `logger_resp_immediate`) with explicit acks, so interest retention keeps messages while the logger is down (up to the 24 h `max_age`). Failed decrypts or database inserts are redelivered; invalid envelopes are terminated.

## Upgrading from 0.0.x

- Breaking: only Edge Protocol 1.0 messages are logged; upgrade edges to puda SDK 0.1.0rc1+ and the CLI to 0.2.0-rc1+.
- `command_log` has a new `protocol_version TEXT NOT NULL` column. `init.sql` only runs on a fresh database, so migrate existing ones:
  `ALTER TABLE command_log ADD COLUMN protocol_version TEXT NOT NULL DEFAULT '0.0'; ALTER TABLE command_log ALTER COLUMN protocol_version DROP DEFAULT;`
- Provision streams with `setup_streams.sh` before starting the logger; it no longer works against an unprovisioned broker.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `NATS_SERVERS` | — | Comma-separated list of NATS server URLs (required) |
| `POSTGRES_HOST` | — | PostgreSQL host (required) |
| `POSTGRES_PORT` | — | PostgreSQL port (required) |
| `POSTGRES_DB` | — | PostgreSQL database name (required) |
| `POSTGRES_USER` | — | PostgreSQL user (required) |
| `POSTGRES_PASSWORD` | — | PostgreSQL password (required) |
| `PUDA_NATS_CA` | unset | TLS CA file for `tls://` servers; requires `PUDA_E2E_KEY_FILE` |
| `PUDA_E2E_KEY_FILE` | unset | Lab payload key file (`encrypt=<base64 32-byte key>`); requires `PUDA_NATS_CA` |

Copy `.env.example` to `.env` and adjust values as needed.

### E2E (TLS + payload encryption)

- Both `PUDA_NATS_CA` and `PUDA_E2E_KEY_FILE` unset: plaintext, all `NATS_SERVERS` must be `nats://`.
- Both set: TLS + encrypted payloads, all `NATS_SERVERS` must be `tls://` (e.g. the pudadev broker). Plaintext payloads are refused.
- Setting only one, mixing URL schemes, or missing/invalid files is a startup error. Encryption never falls back to plaintext.
- Key rotation follows KV `E2E_KEYRING/current` (polled every 2 s and on a decrypt failure); the key file and its directory must be writable so rotated keys persist. Give the logger its own copy of the lab key (`chmod 600`).
- With Docker Compose, set the variables in `.env` to **host** paths; Compose mounts the CA read-only and the key file writable and passes the container paths.

## Running

### Docker Compose

```bash
docker compose up -d
```

The logger uses `network_mode: host` and connects to PostgreSQL via `POSTGRES_HOST` / `POSTGRES_PORT` in `.env`. Start the PostgreSQL server separately from `../server`.

### Local

```bash
pip install .
python main.py
```

### Tests

Unit tests mock NATS and PostgreSQL:

```bash
uv run pytest
```

## Dev

Building docker image and pushing to ghcr:

```bash
docker compose build
docker push ghcr.io/pudap/postgres-logger:latest
```

## Features

- **Durable subscriptions**: Uses durable consumers to ensure no messages are lost
- **Auto-reconnection**: Automatically reconnects to NATS if connection is lost
- **Error handling**: Gracefully handles parsing errors and continues logging
- **Indexed queries**: Database tables include indexes for efficient querying by machine_id, run_id, and timestamps
