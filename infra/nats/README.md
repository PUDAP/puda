# NATS Cluster setup

1. Copy the template: `cp .env.example .env`

2. Edit `.env` and fill in the real values specific to that machine.

3. `docker compose up -d`

## JetStream streams

Declarative stream configs live in [`streams/`](./streams/). Apply them with:

```bash
NATS_URL=nats://localhost:4222 ./setup_streams.sh
```

These match the Python SDK / Go CLI:

| Stream | Subjects | Retention |
|--------|----------|-----------|
| `COMMAND_QUEUE` | `puda.*.cmd.queue` | workqueue |
| `COMMAND_IMMEDIATE` | `puda.*.cmd.immediate` | workqueue |
| `RESPONSE_QUEUE` | `puda.*.cmd.response.queue` | interest |
| `RESPONSE_IMMEDIATE` | `puda.*.cmd.response.immediate` | interest |

Subjects are lowercase `puda.*` (case-sensitive). Events/telemetry stay on core NATS — no JetStream streams.

Optional compose one-shot (mount both the script and `streams/`):

```yaml
services:
  nats-setup:
    image: natsio/nats-box
    depends_on:
      - nats
    volumes:
      - ./setup_streams.sh:/setup_streams.sh:ro
      - ./streams:/streams:ro
    environment:
      - NATS_URL=nats://nats:4222
      - STREAMS_DIR=/streams
    command: ["sh", "/setup_streams.sh"]
```
