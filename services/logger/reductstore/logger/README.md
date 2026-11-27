# reductstore-logger

Streams PUDA NATS machine traffic to [ReductStore](https://www.reduct.store/).

Requires **PUDA Edge Protocol 1.0** (`docs/edge-protocol/edge-protocol-v1.0.md`):
puda SDK `0.1.0rc1`+ on edges and CLI `0.2.0-rc1`+. Logger version 1.0.0 has no
compatibility with 0.1.x setups (CLI 0.1.x, SDK 0.0.x).

## Upgrading to 0.2.x

- Upgrade edges (SDK 0.1.0rc1) and the CLI (0.2.0-rc1) first; older envelopes
  and telemetry are now dropped as invalid.
- The `nats-stream-init` compose service is gone. Provision streams with
  `infra/nats/jetstream/setup_streams.sh`; the logger never updates or deletes
  them (it only creates a missing response stream, with a warning).
- Immediate commands are recorded from `RESPONSE_IMMEDIATE` only; the logger no
  longer subscribes to `puda.*.cmd.*`. The `version` handling is replaced by the
  `protocol_version` label.
- Durable consumer names are unchanged, so existing cursors are kept.
- Raw-body dashboards: telemetry bodies are always `{timestamp, data: {...}}`.

Each NATS message is stored as a timestamped JSON record with InfluxDB-style labels for filtering. The raw payload is kept intact (ReductStore is blob storage), unlike the Telegraf logger which extracts scalar fields.

## Entries

| Entry | NATS subjects | Description |
|---|---|---|
| `commands` | `puda.*.cmd.queue` (queued requests), `puda.*.cmd.response.*` (responses) | Command/response log |
| `telemetry` | `puda.*.tlm.health` | Machine health metrics |
| `stream__<machine_id>__<name>` | `puda.<machine_id>.tlm.stream.<name>` | Named telemetry streams, one entry per machine and stream |

### `commands` labels

| Label | Source |
|---|---|
| `machine_id` | `header.machine_id` (fallback: parsed from NATS subject) |
| `topic` | parsed from NATS subject (`queue`, `response.immediate`, `response.queue`) |
| `cmd_name` | `command.name` |
| `msg_type` | static (`command` or `response`) |
| `status` | `sent` for requests; `response.status` for responses |
| `protocol_version` | `header.protocol_version` (e.g. `1.0`) |
| `username` | `header.username` |
| `run_id` | `header.run_id` |
| `subject` | NATS subject |
| `user_id` | `header.user_id` |
| `step_number` | `command.step_number` |
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
| `cpu` | `data.cpu` (when present) |
| `mem` | `data.mem` (when present) |
| `temp` | `data.temp` (when present) |
| `status` | `data.status` (when present) |

Telemetry stream entries carry `machine_id`, `stream` and `subject` labels.

Commands and responses must be protocol 1.0 envelopes (`header` and `command`
objects; responses also `response`). Telemetry must use the `{timestamp, data:
{...}}` wrapper (§12). Anything else is logged and dropped (JetStream
deliveries are terminated). The opened JSON body is stored unchanged.

Record timestamps come from `header.timestamp` (commands) or the outer `timestamp` (telemetry). ReductStore requires unique timestamps per entry; collisions increment by 1 µs.

## NATS subscription model

Queued command **requests** (`puda.*.cmd.queue`) use a plain core NATS subscription. `COMMAND_QUEUE` uses WorkQueue retention, so only the machine's consumer may bind to it; a core subscription observes publishes without competing for deliveries.

The logger never subscribes to `puda.*.cmd.immediate` (§8.3: any subscriber creates interest, so the broker stops answering "no responders" for offline machines), `cmd.ping` or `update`. Immediate commands are recorded from their responses on `RESPONSE_IMMEDIATE`, which carry the full header and command.

Command **responses** (`puda.*.cmd.response.*`) use durable push consumers on the provisioned `RESPONSE_QUEUE` / `RESPONSE_IMMEDIATE` streams (interest retention, so messages are kept while the logger is down). At startup the logger checks each stream with `STREAM.INFO`: a missing stream is created with the spec settings (interest, file storage, 24 h `max_age`) and a warning; a `workqueue` stream is a startup error; any other mismatch is logged and left unchanged. The durables are created explicitly if missing and bound with `subscribe_bind`, so no stream or consumer is created implicitly.

Durable names are `reductstore_logger_resp_queue` and `reductstore_logger_resp_immediate` so this logger does not share consumers with the InfluxDB or PostgreSQL loggers.

Telemetry (`puda.*.tlm.health`, `puda.*.tlm.stream.>`) uses core NATS subscriptions.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `NATS_SERVERS` | — | Comma-separated NATS server URLs; all `nats://` (plaintext) or all `tls://` (E2EE) |
| `PUDA_NATS_CA` | unset | TLS CA file; requires `PUDA_E2E_KEY_FILE` too |
| `PUDA_E2E_KEY_FILE` | unset | PUDA E2E key file (§13.1); requires `PUDA_NATS_CA` too. Must be writable (key rotation) |
| `REDUCTSTORE_URL` | `http://localhost:8383` | ReductStore HTTP URL |
| `REDUCTSTORE_TOKEN` | `reduct` | API token (`RS_API_TOKEN` on the server) |
| `REDUCTSTORE_BUCKET` | `puda` | Target bucket (created on startup if missing) |

### E2EE

If both `PUDA_NATS_CA` and `PUDA_E2E_KEY_FILE` are unset, the logger runs in
plaintext and rejects sealed payloads. If both are set, it connects over TLS,
opens every payload with `puda.e2e.Context`, follows key rotation from KV
`E2E_KEYRING/current` (polled every 2 s, persisted to the key file) and rejects
plaintext. Setting only one is a startup error. In compose, set them to host
paths in `.env`; they are mounted into the container.

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
uv sync
uv run python main.py
```

### Tests

```bash
uv run pytest
```
