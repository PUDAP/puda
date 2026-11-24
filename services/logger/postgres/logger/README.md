# postgres-logger

Listens to NATS response streams and logs all command responses to PostgreSQL.

## Overview

The logger subscribes to:
- `puda.*.cmd.response.queue`
- `puda.*.cmd.response.immediate`

It extracts response data and stores them in PostgreSQL:
- `command_log`: Stores all command responses received from machines

Note: The service only listens to response streams (`{namespace}.*.cmd.response.*`), not command streams.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `NATS_SERVERS` | — | Comma-separated list of NATS server URLs (required) |
| `POSTGRES_HOST` | — | PostgreSQL host (required) |
| `POSTGRES_PORT` | — | PostgreSQL port (required) |
| `POSTGRES_DB` | — | PostgreSQL database name (required) |
| `POSTGRES_USER` | — | PostgreSQL user (required) |
| `POSTGRES_PASSWORD` | — | PostgreSQL password (required) |

Copy `.env.example` to `.env` and adjust values as needed.

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
