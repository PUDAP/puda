# Logger Service

A service that listens to NATS response streams and logs all command responses to PostgreSQL database.

## Overview

The logger service subscribes to:
- Response streams: `puda.*.cmd.response.queue` and `puda.*.cmd.response.immediate`

It extracts response data and stores them in PostgreSQL:
- `response_log`: Stores all responses received from machines

Note: The service only listens to response streams (`{namespace}.*.cmd.response.*`), not command streams.

## Configuration

The service can be configured via environment variables:

- `NATS_SERVERS`: Comma-separated list of NATS server URLs (default: `nats://localhost:4222`)
- `POSTGRES_HOST`: PostgreSQL host (default: `localhost`)
- `POSTGRES_PORT`: PostgreSQL port (default: `5432`)
- `POSTGRES_DB`: PostgreSQL database name (default: `puda`)
- `POSTGRES_USER`: PostgreSQL user (default: `puda`)
- `POSTGRES_PASSWORD`: PostgreSQL password (required)

## Database Schema

The service uses the following table:

### response_log
- `log_id`: UUID primary key
- `machine_id`: Machine identifier (references `machine` table)
- `response_type`: 'queue' or 'immediate'
- `command`: Command name
- `run_id`: Optional run ID
- `command_id`: Optional command ID
- `status`: Response status ('success' or 'error')
- `error`: Optional error message
- `completed_at`: Completion timestamp
- `full_payload`: Full message payload (JSONB)
- `created_at`: Record creation timestamp

## Running

### Using Docker Compose

```bash
cd services/logger
docker compose up -d
```

### Running Locally

```bash
cd services/logger
uv sync
uv run python logger.py
```

## Features

- **Durable subscriptions**: Uses durable consumers to ensure no messages are lost
- **Auto-reconnection**: Automatically reconnects to NATS if connection is lost
- **Error handling**: Gracefully handles parsing errors and continues logging
- **Indexed queries**: Database tables include indexes for efficient querying by machine_id, run_id, command_id, and timestamps

