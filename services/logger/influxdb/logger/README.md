# influxdb-logger

Streams PUDA NATS machine traffic to InfluxDB using a Python subscriber and
[Telegraf](https://docs.influxdata.com/telegraf/). The subscriber decrypts messages
when configured, maps them to Influx line protocol, and writes to Telegraf's
`inputs.execd` over a local pipe. Telegraf buffers, batches, and writes to InfluxDB.

## Measurements

| Measurement | NATS subjects | Description |
|---|---|---|
| `commands` | `puda.*.cmd.*` (requests), `puda.*.cmd.response.*` (responses) | Command/response log |
| `telemetry` | `puda.*.tlm.health` | Machine health metrics (`cpu`, `mem`, `temp`), stored as a **60s mean** per machine |
| `telemetry_stream` | `puda.*.tlm.stream.>` | Driver telemetry samples, stored individually without averaging |

### `commands` fields and tags

| Kind | Name | Source |
|---|---|---|
| tag | `machine_id` | `header.machine_id` |
| tag | `topic` | parsed from NATS subject (`immediate`, `queue`, `response.immediate`, `response.queue`) |
| tag | `cmd_name` | `command.name` |
| tag | `msg_type` | static (`command` or `response`) |
| tag | `status` | `sent` for requests; `response.status` for responses |
| tag | `run_id` | `header.run_id` (when present) |
| tag | `username` | `header.username` (when present) |
| field | `user_id` | `header.user_id` |
| field | `step_number` | `command.step_number` |
| field | `cmd_version` | `command.version` |
| field | `response_code` | `response.code` (responses only) |
| field | `response_message` | `response.message`, or `response.data` when message is empty (responses only) |
| field | `completed_at` | `response.completed_at` (responses only) |

Tags identify the context used to group/filter commands, including `run_id` and `username`. A run ID is shared by the commands within a run, and a username can recur across runs. InfluxDB 3 does not have the same tag-cardinality limitation as older engines. The subscriber adds a `subject` tag internally and drops it on write (`tagexclude`).

This matches existing `commands` tables with `run_id` / `username` tags. If a deployment previously stored them as fields, migrate or use a new table/database before switching: InfluxDB 3 cannot change an existing field into a tag in place. Back up historical data before rebuilding any table.

### `telemetry_stream` fields and tags

Driver streams use the SDK's `puda.<machine_id>.tlm.stream.<name>` subjects,
including position on `tlm.stream.pos`. Each sample is stored without health
averaging, with `machine_id` and `stream` tags and a single `data` string field
containing the complete JSON object. Nested objects, arrays, nulls, and original
JSON value types are preserved; empty objects are accepted. Invalid JSON and
non-finite numbers are rejected. Position, weight, and other streams can share
the table without conflicts between their payload field names or types.
An optional RFC3339 `timestamp` supplies the point time; otherwise the logger
uses receipt time. The timestamp also remains in `data`. This works identically
with plaintext and E2EE payloads. Numeric charts must extract values from `data`.

For the new SDK `{timestamp, data: {...}}` wire envelope, the subscriber unwraps
the inner object once for stream `data` and health scalar/status extraction;
point time comes from the outer timestamp. Legacy flattened messages continue
to work as described above, including retaining their timestamp in stream JSON.
Detection requires exactly the two outer keys and object-valued `data`; legacy
`data` measurements with extra siblings are not unwrapped. A legacy object with
only those two keys is ambiguous and treated as the new envelope. Upgrade this
subscriber before SDK publishers; audit custom consumers and timestamp queries.

Existing tables with scalar columns (such as `x`, `y`, or `mass_g`) can keep their
historical rows. New samples populate `data`, leaving those old columns null;
historical rows are not backfilled. No table deletion is needed, provided an
existing `data` column is absent or already a string field (not a tag).

### `telemetry` fields and tags

The current SDK publishes host health every 5 seconds by default. Telegraf keeps that live subscription but **writes one aggregated point per machine per 60s** (`aggregators.basicstats` with `stats = ["mean"]` and `drop_original = true`). A rename processor removes the `_mean` suffix so field names stay `cpu` / `mem` / `temp`. Grafana queries do not need to change, but resolution is 1 minute and points appear shortly after each window closes.

| Kind | Name | Source |
|---|---|---|
| tag | `machine_id` | parsed from NATS subject |
| tag | `status` | `status` (string, when present). A tag so it survives mean aggregation; a status change inside the window emits one point per status |
| field | `cpu` | 60s mean of `cpu` (float, when present) |
| field | `mem` | 60s mean of `mem` (float, when present) |
| field | `temp` | 60s mean of `temp` (float, when present; omitted if JSON `null`) |
| field | `data` | raw JSON, **only** if none of the fields above were present (not aggregated; dropped with the original health samples) |

Shared health scalars are extracted so Grafana can chart them without storing a duplicate JSON blob on every health sample. Machine-specific extras in health payloads are not stored; publish driver data on `tlm.stream.<name>` to retain it in `telemetry_stream`.

`connected` is not extracted or averaged from health messages. The current SDK's
host-health publisher sends only `cpu`, `mem`, and `temp`. Use heartbeat or
health-message freshness for availability; driver-specific connection state is
preserved unchanged inside telemetry stream JSON payloads.

NATS messages use the raw PUDA SDK wire format. The subscriber extracts fields before handing metrics to Telegraf.

## NATS subscription model

Command **requests** (`puda.*.cmd.queue` and `puda.*.cmd.immediate`) use core NATS
subscriptions. They observe traffic without binding to or acknowledging the
machines' WorkQueue consumers. Health and driver telemetry also use core NATS.

Command **responses** use shared durable push queue consumers on `RESPONSE_QUEUE`
and `RESPONSE_IMMEDIATE` with limits retention (default 24h). Durable names and queue
groups remain `puda_logger_cmd_responses_queue` and `puda_logger_cmd_responses_immediate`.
The subscriber initializes streams and consumers using the same TLS settings,
preserving existing delivery subjects and acknowledgment positions. It sets limits
retention, maximum age, and the configurable acknowledgment window, as the upstream
init job did. Commands' WorkQueue streams are not changed.

Responses published while the logger is offline are replayed within stream retention.
Acknowledgment follows stdout handoff, **not confirmation of an InfluxDB write**.
Crashes or exhausted Telegraf buffers can still lose data, and redelivery can produce
duplicates. Core command requests, health, and driver telemetry remain live-only.

`LOGGER_REPLICAS` controls Compose scaling; all replicas share queue groups.
Healthchecks query the durable acknowledgment windows using the configured TLS
settings, and the existing autoheal service restarts unhealthy replicas.
The separate `nats-stream-init` service is no longer required; initialization runs
in the subscriber. `/nats-init.sh` remains available inside the image for manual
initialization. With multiple replicas, health means cover each replica's samples;
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
| `JS_RESPONSE_MAX_AGE` | `24h` | Response stream retention age, e.g. `30m`, `24h`, `1h30m` |
| `NATS_SERVERS` | — | Comma-separated NATS server URLs |
| `PUDA_NATS_CA` | unset | Optional TLS CA file path; requires the key file variable too |
| `PUDA_E2E_KEY_FILE` | unset | Optional shared PUDA key file path; requires the CA variable too |

There is no E2EE boolean. If both optional variables are unset or empty, use
`nats://` URLs and plaintext payloads. If both are set, use `tls://` URLs and
encrypted payloads. Setting only one, mixing URL schemes, or supplying missing or
invalid files fails startup. Encryption never silently falls back to plaintext.

The logger pins the E2EE-capable PUDA SDK `0.0.19rc1` and reuses its framing,
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

## Development and tests

```bash
uv sync --frozen
uv run pytest -q
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
