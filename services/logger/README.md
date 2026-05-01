# Logger Service

A service that listens to NATS response streams and logs all command responses to a PostgreSQL database for backup

## Overview

The logger service subscribes to:
- Response streams: `puda.*.cmd.response.queue` and `puda.*.cmd.response.immediate`

It extracts response data and stores them in PostgreSQL:
- `command_log`: Stores all command responses received from machines

Note: The service only listens to response streams (`{namespace}.*.cmd.response.*`), not command streams.

## Configuration

The service and its bundled PostgreSQL database can be configured via environment variables:

- `NATS_SERVERS`: Comma-separated list of NATS server URLs
- `POSTGRES_HOST`: PostgreSQL host (default: `postgres` in Docker Compose)
- `POSTGRES_PORT`: PostgreSQL port (default: `5432` in Docker Compose)
- `POSTGRES_DB`: PostgreSQL database name (default: `puda`)
- `POSTGRES_USER`: PostgreSQL user (default: `postgres`)
- `POSTGRES_PASSWORD`: PostgreSQL password (default: `postgres`)

Docker Compose loads `.env.example` by default and overlays `.env` when present. For local runs outside Docker, copy `.env.example` to `.env` and adjust values as needed.

## Running

### Using Docker Compose

```bash
cd services/logger
docker compose up -d
```

This starts both the logger and its PostgreSQL database. The database is exposed on host port `5433` and uses the `postgres_data` Docker volume mounted at `/var/lib/postgresql` for PostgreSQL 18+ compatibility. The initial schema is loaded from `init.sql` on first startup.

### Running Locally

```bash
cd services/logger
uv sync
uv run python main.py
```

For local runs outside Docker, point `POSTGRES_HOST` and `POSTGRES_PORT` at a reachable PostgreSQL instance.

## Dev

Building docker image and pushing to ghcr
```bash
docker compose build
docker push ghcr.io/pudap/logger:latest
```

## Features

- **Durable subscriptions**: Uses durable consumers to ensure no messages are lost
- **Auto-reconnection**: Automatically reconnects to NATS if connection is lost
- **Error handling**: Gracefully handles parsing errors and continues logging
- **Indexed queries**: Database tables include indexes for efficient querying by machine_id, run_id, command_id, and timestamps

