# reductstore-logger

Streams PUDA NATS machine traffic to [ReductStore](https://www.reduct.store/).

Each NATS message is stored as a timestamped JSON record with InfluxDB-style labels for filtering. The raw payload is kept intact (ReductStore is blob storage), unlike the Telegraf logger which extracts scalar fields.

## Entries

| Entry | NATS subjects | Description |
|---|---|---|
| `commands` | `puda.*.cmd.*` (requests), `puda.*.cmd.response.*` (responses) | Command/response log |
| `telemetry` | `puda.*.tlm.health` | Machine health metrics |

### `commands` labels

| Label | Source |
|---|---|
| `machine_id` | `header.machine_id` (fallback: parsed from NATS subject) |
| `topic` | parsed from NATS subject (`immediate`, `queue`, `response.immediate`, `response.queue`) |
| `cmd_name` | `command.name` |
| `msg_type` | static (`command` or `response`) |
| `status` | `sent` for requests; `response.status` for responses |
| `username` | `header.username` |
| `run_id` | `header.run_id` |
| `subject` | NATS subject |
| `user_id` | `header.user_id` |
| `step_number` | `command.step_number` |
| `cmd_version` | `command.version` |
| `response_code` | `response.code` (responses only) |
| `completed_at` | `response.completed_at` (responses only) |
| `response` | `response.message`, or `response.data` when message is empty, or `response.code` (responses only; truncated at 4000 chars). Commas are stored as `;` so Grafana's batch label parser does not split the value. |

The original NATS JSON is stored unchanged as the record body. Grafana's
ReductStore plugin flattens JSON content into one column per leaf, so the
dashboard reads the `response` label — the same value as the Influx
`response_message` / `response_code` coalesce on the machine command logs.

### `telemetry` labels

| Label | Source |
|---|---|
| `machine_id` | parsed from NATS subject |
| `subject` | NATS subject |
| `cpu` | `cpu` (when present) |
| `mem` | `mem` (when present) |
| `temp` | `temp` (when present) |
| `connected` | `connected` (when present) |
| `status` | `status` (when present) |

NATS messages use the raw `puda-comms` wire format (not the JSON envelope the old Python logger constructed internally). The logger also accepts the older envelope (`{"data": {...}}`) so sample publishers still work.

Record timestamps come from `header.timestamp` (commands) or `timestamp` (telemetry). ReductStore requires unique timestamps per entry; collisions increment by 1 µs.

New SDK health messages use exactly `{timestamp, data: {...}}`: the logger reads
labels from the inner object and record time from the outer timestamp, retaining
the original body unchanged. Old flattened health and the older internal
envelopes remain accepted. Exact two-key, object-valued `data` detection takes
precedence; an identical legacy shape is inherently ambiguous. Upgrade consumers
before SDK publishers. Raw-body dashboards must account for metrics moving
under `data`; command/response mapping and subjects are unchanged. This backend
still subscribes only to health, not named telemetry streams.

## NATS subscription model

Command **requests** (`puda.*.cmd.*`) use a plain core NATS subscription. This is safe because command streams use WorkQueue retention — only the machine's execution consumer may bind as a JetStream consumer; a passive core subscription observes traffic without competing for deliveries.

Command **responses** (`puda.*.cmd.response.*`) use durable JetStream consumers on the `RESPONSE_QUEUE` / `RESPONSE_IMMEDIATE` streams (interest retention). A `nats-stream-init` compose service creates these streams idempotently on startup.

Durable names are `reductstore_logger_resp_queue` and `reductstore_logger_resp_immediate` so this logger does not share consumers with the InfluxDB or PostgreSQL loggers.

Telemetry (`puda.*.tlm.health`) uses a core NATS subscription.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `NATS_SERVERS` | — | Comma-separated NATS server URLs (`nats-stream-init` uses the first entry) |
| `REDUCTSTORE_URL` | `http://localhost:8383` | ReductStore HTTP URL |
| `REDUCTSTORE_TOKEN` | `reduct` | API token (`RS_API_TOKEN` on the server) |
| `REDUCTSTORE_BUCKET` | `puda` | Target bucket (created on startup if missing) |

## Running

### Docker Compose

```bash
cp .env.example .env   # edit with your values
docker compose up -d --build
```

The logger uses `network_mode: host` and connects to ReductStore via `REDUCTSTORE_URL` in `.env`. Start the ReductStore server separately from `../server`.

### Local (without Docker)

```bash
export NATS_SERVERS=nats://localhost:4222
export REDUCTSTORE_URL=http://localhost:8383
export REDUCTSTORE_TOKEN=reduct
export REDUCTSTORE_BUCKET=puda
pip install .
python main.py
```
