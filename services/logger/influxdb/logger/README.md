# influxdb-logger

Streams PUDA NATS machine traffic to InfluxDB using a Python subscriber and
[Telegraf](https://docs.influxdata.com/telegraf/). The subscriber decrypts messages
when configured, maps them to Influx line protocol, and writes to Telegraf's
`inputs.execd` over a local pipe. Telegraf buffers, batches, and writes to InfluxDB.

Requires **PUDA Edge Protocol 1.0** (`docs/edge-protocol/edge-protocol-v1.0.md`):
puda SDK `0.1.0rc1`+ on the edges and CLI `0.2.0-rc1`+. Earlier SDKs and CLIs
are not supported; see [Upgrading to 0.2.x](#upgrading-to-02x).

## Measurements

| Measurement | NATS subjects | Description |
|---|---|---|
| `commands` | `puda.*.cmd.queue` (queued requests), `puda.*.cmd.response.*` (responses) | Command/response log |
| `telemetry` | `puda.*.tlm.health` | Machine health metrics (`cpu`, `mem`, `temp`), stored as a **60s mean** per machine |
| `telemetry_stream` | `puda.*.tlm.stream.>` | Driver telemetry samples, stored individually without averaging |

### `commands` fields and tags

| Kind | Name | Source |
|---|---|---|
| tag | `machine_id` | `header.machine_id` |
| tag | `topic` | parsed from NATS subject (`queue`, `response.immediate`, `response.queue`) |
| tag | `cmd_name` | `command.name` |
| tag | `msg_type` | static (`command` or `response`) |
| tag | `status` | `sent` for requests; `response.status` for responses |
| tag | `protocol_version` | `header.protocol_version` (`MAJOR.MINOR`; absent only on an edge's reply to a malformed command) |
| tag | `run_id` | `header.run_id` (when present) |
| tag | `username` | `header.username` (when present) |
| field | `user_id` | `header.user_id` |
| field | `step_number` | `command.step_number` |
| field | `response_code` | `response.code` (responses only) |
| field | `response_message` | `response.message`, or `response.data` when message is empty (responses only) |
| field | `completed_at` | `response.completed_at` (responses only) |

A `header.protocol_version` that is not `MAJOR.MINOR` makes the message invalid and it is dropped. A missing one is logged without the tag, because an edge's `EXECUTION_ERROR` reply to a malformed command echoes the command as received (spec §8.4).
The tag records the version as sent, so a major mismatch stays visible. Immediate
commands appear only as `response.immediate` rows (§8.3).

Tags identify the context used to group/filter commands, including `run_id` and `username`. A run ID is shared by the commands within a run, and a username can recur across runs. InfluxDB 3 does not have the same tag-cardinality limitation as older engines. The subscriber adds a `subject` tag internally and drops it on write (`tagexclude`).

This matches existing `commands` tables with `run_id` / `username` tags. If a deployment previously stored them as fields, migrate or use a new table/database before switching: InfluxDB 3 cannot change an existing field into a tag in place. Back up historical data before rebuilding any table.

### `telemetry_stream` fields and tags

Driver streams use the SDK's `puda.<machine_id>.tlm.stream.<name>` subjects,
including position on `tlm.stream.pos`. Each sample is stored without health
averaging, with `machine_id` and `stream` tags and a single `data` string field
containing the wrapper's complete `data` object. Nested objects, arrays, nulls, and
original JSON value types are preserved; empty objects are accepted. Invalid JSON and
non-finite numbers are rejected. Position, weight, and other streams can share
the table without conflicts between their payload field names or types.
This works identically with plaintext and E2EE payloads. Numeric charts must
extract values from `data`.

Telemetry always uses the protocol's `{timestamp, data: {...}}` wrapper (§12).
The RFC3339 `timestamp` supplies the point time. A message without the wrapper
(a missing or invalid `timestamp`, or a non-object `data`) is logged and dropped.

Existing tables with scalar columns (such as `x`, `y`, or `mass_g`) can keep their
historical rows. New samples populate `data`, leaving those old columns null;
historical rows are not backfilled. No table deletion is needed, provided an
existing `data` column is absent or already a string field (not a tag).

### `telemetry` fields and tags

The current SDK publishes host health every 5 seconds by default. Telegraf keeps that live subscription but **writes one aggregated point per machine per 60s** (`aggregators.basicstats` with `stats = ["mean"]` and `drop_original = true`). A rename processor removes the `_mean` suffix so field names stay `cpu` / `mem` / `temp`. Grafana queries do not need to change, but resolution is 1 minute and points appear shortly after each window closes.

| Kind | Name | Source |
|---|---|---|
| tag | `machine_id` | parsed from NATS subject |
| tag | `status` | `data.status` (string, when present). A tag so it survives mean aggregation; a status change inside the window emits one point per status |
| field | `cpu` | 60s mean of `data.cpu` (float, when present) |
| field | `mem` | 60s mean of `data.mem` (float, when present) |
| field | `temp` | 60s mean of `data.temp` (float, when present; omitted if JSON `null`) |
| field | `data` | raw message JSON, **only** if none of the fields above were present (not aggregated; dropped with the original health samples) |

Shared health scalars are extracted so Grafana can chart them without storing a duplicate JSON blob on every health sample. Machine-specific extras in health payloads are not stored; publish driver data on `tlm.stream.<name>` to retain it in `telemetry_stream`.

`connected` is not extracted or averaged from health messages. The current SDK's
host-health publisher sends only `cpu`, `mem`, and `temp`. Use heartbeat or
health-message freshness for availability; driver-specific connection state is
preserved unchanged inside telemetry stream JSON payloads.

NATS messages use the raw PUDA SDK wire format. The subscriber extracts fields before handing metrics to Telegraf.

## NATS subscription model

Queued command **requests** (`puda.*.cmd.queue`) use core NATS
subscriptions. Immediate commands are not tapped: they are core request/reply,
and any extra subscriber on `cmd.immediate` stops the broker answering "no
responders" for an offline machine; their `RESPONSE_IMMEDIATE` copy carries
the full command. They observe traffic without binding to or acknowledging the
machines' WorkQueue consumers. Health and driver telemetry also use core NATS.

Command **responses** use shared durable push queue consumers on `RESPONSE_QUEUE`
and `RESPONSE_IMMEDIATE`. Durable names and queue groups remain
`puda_logger_cmd_responses_queue` and `puda_logger_cmd_responses_immediate`.
The subscriber never subscribes to `cmd.immediate`, `cmd.ping` or `update` subjects.

The response streams belong to the provisioner (`infra/nats/jetstream/setup_streams.sh`,
§5): interest retention, file storage, 24h max age. The subscriber never updates or
deletes a stream. On startup it checks both streams with `STREAM.INFO`:

- Missing: creates it with those settings and logs that the broker is unprovisioned.
- Wrong subject or workqueue retention: refuses to start (acknowledging would delete
  messages other readers need).
- Other differences: logs the mismatch and leaves the stream unchanged.

It creates or updates only its own consumers, preserving existing delivery subjects
and acknowledgment positions, and sets the configurable acknowledgment window.

Responses published while the logger is offline are replayed within the 24h max age.
Acknowledgment follows stdout handoff, **not confirmation of an InfluxDB write**.
Crashes or exhausted Telegraf buffers can still lose data, and redelivery can produce
duplicates. Core command requests, health, and driver telemetry remain live-only.

`LOGGER_REPLICAS` controls Compose scaling; all replicas share queue groups.
Healthchecks query the durable acknowledgment windows using the configured TLS
settings, and the existing autoheal service restarts unhealthy replicas.
The separate `nats-stream-init` service is no longer required; stream checks and
consumer setup run in the subscriber. `/nats-init.sh` remains available inside the
image to run the same checks manually. With multiple replicas, health means cover each replica's samples;
queries should combine them by machine as in the upstream configuration.

Decryption failures are logged without payloads or keys. Responses are negatively
acknowledged with a five-second delay (at most five deliveries); malformed JSON or
schema errors terminate delivery. Core messages cannot be replayed. NATS pending
queues and the Python queue are bounded; slow-consumer errors are logged. Telegraf
restarts a failed subscriber after ten seconds.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `INFLUXDB_URL` | `http://localhost:8181` | InfluxDB 3 Core URL |
| `INFLUXDB_TOKEN` | — | Auth token |
| `INFLUXDB_DATABASE` | `puda` | Target database (written as `bucket` in `outputs.influxdb_v2`) |
| `INFLUXDB_ORGANIZATION` | `bears` | Organization name for `outputs.influxdb_v2` |
| `LOGGER_REPLICAS` | `1` | Logger replicas sharing NATS queue groups |
| `JS_MAX_ACK_PENDING` | `20000` | Maximum outstanding response acknowledgments |
| `NATS_SERVERS` | — | Comma-separated NATS server URLs |
| `PUDA_NATS_CA` | unset | Optional TLS CA file path; requires the key file variable too |
| `PUDA_E2E_KEY_FILE` | unset | Optional shared PUDA key file path; requires the CA variable too |

There is no E2EE boolean. If both optional variables are unset or empty, use
`nats://` URLs and plaintext payloads. If both are set, use `tls://` URLs and
encrypted payloads. Setting only one, mixing URL schemes, or supplying missing or
invalid files fails startup. Encryption never silently falls back to plaintext.

The logger pins PUDA SDK `0.1.0rc1` (Edge Protocol 1.0) and reuses its framing,
subject authentication, and keyring functions. It polls `E2E_KEYRING/current`
every two seconds and refreshes again on a decryption failure. The shared key file
must be writable so rotated keys persist across restarts. Its runtime directory
must also be writable for the SDK's `.id` metadata. Give the logger its own copy
of the lab key file.

## Running

### Docker Compose

```bash
cp .env.example .env   # edit with your values
docker compose up -d --build   # first run, or after Dockerfile/entrypoint changes
```

The same Compose file supports both modes. For plaintext, leave both optional
variables unset; no certificate or key files are needed.

For E2EE, set `.env` to your TLS broker URLs and the **local machine paths** of the
broker CA and a copy of the shared lab key:

```dotenv
NATS_SERVERS=tls://your-broker:4222
PUDA_NATS_CA=/path/to/ca.pem
PUDA_E2E_KEY_FILE=/path/to/e2e.key
```

The key file contains `encrypt=<base64-encoded 32-byte key>`. Restrict its permissions
to the service user (for example, `chmod 600 /path/to/e2e.key`). Then run:

```bash
docker compose up -d --build
```

Compose mounts the CA read-only and the key file writable, and automatically
replaces the environment values with the corresponding container paths. Key
rotation updates the local key file in place. The SDK's `.id` metadata stays in
the container; this logger does not use it for registration. Missing source paths
fail instead of being created as directories. For plaintext mode, Compose uses
unused `/dev/null` mounts and passes empty environment values.

**Config changes:** `telegraf.conf.template` is mounted into the container. After editing it, restart without rebuilding:

```bash
docker compose restart influxdb-logger
```

### Local (without Docker)

Install Python 3.11+, `uv`, and Telegraf. Run `uv sync --frozen`, export your
environment variables, and configure Telegraf's `inputs.execd.command` with the
absolute paths to `.venv/bin/python` and `subscriber.py`. Use `signal = "none"`
and `data_format = "influx"`. Render the InfluxDB environment placeholders in the
template with `envsubst`, then run Telegraf with that configuration. For E2EE,
use the same local CA and key file paths as in the Docker setup.

To inspect the subscriber's line protocol directly:

```bash
NATS_SERVERS=nats://localhost:4222 uv run python subscriber.py
```

## Upgrading to 0.2.x

This is a breaking release for Edge Protocol 1.0; there is no backward compatibility.

- **Stream ownership:** the logger no longer forces limits retention or a max age on
  `RESPONSE_QUEUE`/`RESPONSE_IMMEDIATE`. Provision them with `setup_streams.sh`;
  existing limits streams are left as they are, with a logged mismatch.
- **Removed `JS_RESPONSE_MAX_AGE`:** retention age comes from provisioning (24h).
  Delete the variable from `.env`.
- **`protocol_version` tag:** `commands` rows carry `header.protocol_version`. An
  edge's reply to a malformed command, which may lack it, is logged without the tag.
- **Dropped `cmd_version`:** the 1.0 envelope has no `header.version` or
  `command.version`, so nothing is recorded for them.
- **Dropped legacy telemetry:** flattened `tlm.health`/`tlm.stream.*` messages without
  the `{timestamp, data}` wrapper are dropped. Stream `data` no longer includes the
  timestamp. Upgrade edges to SDK `0.1.0rc1`+.

## Development and tests

```bash
uv sync --frozen
uv run --group dev pytest -q
docker build -t puda-influxdb-e2ee-test:local .
RUN_DOCKER_TESTS=1 uv run pytest -q test/test_integration.py
```

Docker tests create isolated NATS and logger containers, disposable TLS/key files,
and a local Influx-compatible HTTP test endpoint. They cover plaintext and E2EE,
field mappings, rotation, NATS reconnection, subscriber restarts, and output outage
recovery. They remove their containers afterwards. Requires Docker and OpenSSL.

Docker and local development both install from `pyproject.toml` and `uv.lock`.
The Docker build uses `uv sync --frozen --no-dev`. After changing dependencies,
update the lockfile:

```bash
uv lock
```
