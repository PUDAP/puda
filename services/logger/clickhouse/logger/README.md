# PUDA NATS → ClickHouse logger

An opt-in **direct native NATS-engine + SQL E2EE ingestion path** is implemented
and tested locally; see [NATIVE.md](NATIVE.md) for control-plane commands,
acceptance coverage and deployment gates. The Python logger below remains the
unchanged rollback path; native ingestion is not enabled by this Compose file.

Python 3.11+ and `puda==0.0.19rc1`, matching the existing InfluxDB logger's E2EE
wire implementation. No Telegraf or ClickHouse client SDK is required. The
standard-library HTTP transport sends `JSONEachRow` batches synchronously with
`async_insert=0` and `wait_end_of_query=1`; it checks both HTTP status and an empty
INSERT response body before acknowledging any response messages.

## Python file roles

All five original top-level Python files are used; they are not five competing
workers. The refactor adds one pure-SQL module:

| File | Purpose / when used |
|---|---|
| `subscriber.py` | **Default Docker entrypoint and rollback data path**: Python subscriptions, E2EE/keyring handling, batching and response ACKs. |
| `storage.py` | Shared configuration, HTTP client and Python wire normalization; used by the subscriber, native control CLI and migration tooling. |
| `backfill.py` | **Optional offline migration CLI**: converts exported legacy rows into split-table JSONEachRow files. Not a running service or part of the Docker image. |
| `native_control.py` | **Opt-in native control CLI**: private-key bootstrap, installation and one-shot encrypted KV key sync. Never subscribes to data messages. |
| `native_ingest.py` | Native control helpers: private key files, historical-key synchronization and separate pull-consumer provisioning. Retains existing SQL imports as compatibility exports. |
| `native_sql.py` | Pure native DDL and directly reusable SELECT builders, including SQL E2EE/normalization and endpoint/path validation. No filesystem or network I/O. |

Docker still copies only `subscriber.py` and `storage.py` and starts the Python
subscriber. Native ingestion requires explicit operator installation; it is not
a default-path replacement. Keep the Python deployment for rollback, and avoid
running both into the same destination unless duplicate rows are intentional.
See [NATIVE.md](NATIVE.md) for local-only acceptance and unresolved production
gates, and [MIGRATION.md](../server/MIGRATION.md) for optional legacy backfill.

## Configure and run

Start [the server](../server/README.md) first. In this directory:

```sh
cp -n .env.example .env
chmod 600 .env
# Edit NATS_SERVERS and CLICKHOUSE_PASSWORD (or separate writer credentials).
# Plaintext: nats://host:port and leave both PUDA_* security files empty.
docker compose config --quiet
docker compose build
docker compose run --rm logger --check-config
docker compose up -d
docker compose logs --tail 50 logger
```

Compose uses **Linux host networking**, with no published ports. Dependencies
are declared in `pyproject.toml` and pinned in `uv.lock`; the Docker build uses
`uv sync --locked --no-dev --no-install-project`, with no requirements file.
Python does not read dotenv files implicitly. For direct execution run
`uv sync --locked`, export environment variables explicitly, then run
`uv run --locked subscriber.py --check-config` to validate without connecting.
`--healthcheck` checks database
credentials and table readability only; it does **not** certify a running NATS
subscriber or recent ingestion. No misleading container healthcheck is provided.
`docker compose stop` allows 75 seconds for SIGTERM/draining the current batches.

`CLICKHOUSE_URL` must be an HTTP(S) origin without inline credentials or a query.
Database/table names are validated SQL identifiers. User and password are required,
not defaulted, and must be printable ASCII for HTTP header authentication. Use HTTPS with a publicly trusted or container-installed CA when
crossing an untrusted network; certificate verification is never disabled.
Redirects and environment HTTP proxies are deliberately disabled to avoid
forwarding credentials. Authentication uses headers, not URL query parameters.
Do not share full Compose config/inspect output; it includes environment secrets.

## Subjects and consumer ownership

| Subjects | Delivery |
|---|---|
| `puda.*.cmd.queue`, `puda.*.cmd.immediate` | Core NATS tap, queue `clickhouse_logger_cmd_requests` |
| `puda.*.tlm.health` | Core NATS, queue `clickhouse_logger_telemetry` |
| `puda.*.tlm.stream.>` | Core NATS, queue `clickhouse_logger_telemetry_stream` |
| `puda.*.cmd.response.queue` | `RESPONSE_QUEUE`, durable/group `clickhouse_logger_responses_queue` |
| `puda.*.cmd.response.immediate` | `RESPONSE_IMMEDIATE`, durable/group `clickhouse_logger_responses_immediate` |

No command WorkQueue consumer is attached or acknowledged. Queue groups and
response delivery subjects (`puda.logger.clickhouse.deliver.*`) are independent
of InfluxDB/ReductStore, so other backends still receive their own copies.
Replicas of this backend share its groups/durables to balance work. Missing
response streams are created with Limits retention and a 24-hour max age;
existing Limits- or Interest-retention streams are validated, **not mutated**.
WorkQueue streams fail closed because logging must not compete with machine
consumers. Interest retention preserves messages only while matching consumer
interest exists; it does not promise replay from before this logger's consumer
was created.
A NATS operator can pre-provision the streams/consumers if the logger lacks
management permissions. Consumers use explicit ACK, 120s ACK wait, unlimited
redeliveries, and the configured maximum unacknowledged window. Existing
incompatible ClickHouse consumers fail closed rather than resetting their cursor.

## Delivery guarantees and failure policy

- Batch flush: `BATCH_SIZE` rows (default 1000) or `BATCH_INTERVAL` seconds
  (default 1). The queue is bounded by `JS_MAX_ACK_PENDING` (default 4096);
  per-subscription pending bytes are bounded to 64 MiB. Tune for message sizes.
- Successful database write precedes response ACK. Failed/uncertain HTTP writes
  NAK durable responses with a 5-second delay. A timeout may have committed:
  **at-least-once**, not exactly-once. Existing stream age/limits can evict messages
  during long outages; monitor broker retention and acknowledgment backlog.
- Core requests/telemetry are live, best-effort taps: downtime, pending-limit
  overflow, process failure or a failed insert can lose them. There is no local
  persistent spool and no promise to replay machine command WorkQueues.
- Invalid JSON, non-object messages, malformed required command fields/timestamps,
  non-finite numbers and non-UTF-8 payloads are discarded; durable responses get
  TERM (not a success ACK), preventing poison-message retry storms. No raw
  payloads, subjects, exception bodies or credentials are logged. Invalid payloads
  are **not** retained in a dead-letter store. Monitor error counts/logs.
- Decryption errors attempt an immediate keyring refresh and retry once; durable
  failures get NAK, never TERM, since the keyring may recover.
- Long processing/backlogs can exceed ACK wait and redeliver. Duplicate rows are
  possible; `event_id` is SHA-256 of subject + NUL + decrypted payload. It is a
  content fingerprint, **not** a unique publisher event ID. Identical legitimate
  messages have the same fingerprint; do not blindly deduplicate telemetry on it.

## Schema and timestamps

`puda.command_logs` keeps commands and responses together, exposing
machine/run/user/command/step/status/topic metadata, including `user_id`,
`username`, and `cmd_version`. `puda.telemetry` exposes machine/time/msg_type/topic
and `stream` (`health` for health; the complete suffix for named streams).
Telemetry `data` is **JSON text in a String**, not ClickHouse native JSON, and has
no fixed CPU/memory/temperature columns. Nested objects, arrays, nulls, status,
and arbitrary measurements survive without schema changes.

Both tables retain the **unchanged decrypted UTF-8 JSON text** in `raw_json`.
Params, nested response data, unknown fields and response completion time remain
queryable with JSON extraction functions. Encryption framing is not retained;
protect the stored plaintext like other lab data. No SDK dependency upgrade is
required to read either telemetry wire shape:

- Legacy flattened `{timestamp, cpu, custom, ...}`: `data` contains all fields
  except the outer timestamp.
- New SDK `{timestamp, data: {...}}`: unwrap the inner object **once**, retaining
  even its own `timestamp` and `data` measurement keys.
- Envelope detection requires **exactly** the two keys `timestamp` and `data`,
  with an object-valued `data`. Extra siblings, a missing timestamp or non-object
  `data` remain legacy fields. There is no invented marker. An old flattened
  payload consisting solely of those two keys with object-valued `data` is
  inherently indistinguishable and is interpreted as the new envelope. Audit
  such publishers before rollout; the original is always retained in `raw_json`.

Commands use `header.timestamp`; telemetry uses the optional outer timestamp,
otherwise receipt time. RFC3339 fractions/offsets use integer arithmetic;
`event_ns` retains nine digits with UTC `DateTime64(9)` materialized `event_time`.
Supported timestamps are nonnegative Int64 nanoseconds (1970 through April
2262). Both append-only MergeTree tables are partitioned monthly, with **no TTL**;
provision retention/backups explicitly. `received_ns` records receipt time.

`CLICKHOUSE_COMMAND_TABLE` and `CLICKHOUSE_TELEMETRY_TABLE` default to
`command_logs` and `telemetry`. They must differ. The retired `CLICKHOUSE_TABLE`
is rejected, even if empty, to prevent a silent cutover. Review the
[non-destructive migration and backfill procedure](../server/MIGRATION.md)
before upgrading an existing installation. The legacy `puda.events` is untouched.

A mixed batch makes two independent synchronous INSERTs, commands first. There
is no cross-table transaction. If the second insert fails, responses are NAKed
even if commands already persisted; redelivery can duplicate those responses.
An empty batch issues no INSERT. Fingerprints are not uniqueness constraints.

## TLS + E2EE and rotation

Set all NATS URLs to `tls://host:port` and set both `PUDA_NATS_CA` and
`PUDA_E2E_KEY_FILE`. Configure `PUDA_E2E_KEY_DIR` to a **dedicated writable directory**
containing `e2e.key`; `PUDA_E2E_KEY_FILE` must refer to that file on the host.
The directory is mounted at `/run/puda-key`, the CA is read-only, and container
paths are injected by Compose. Set LOGGER_UID/GID to the key directory owner's
UID/GID, use directory mode 700 and key mode 600. Do not mount a user's home or a
whole credentials directory. The SDK may create `e2e.key.id`, hence a directory
mount rather than a read-only key mount. Each replica needs its own writable key
copy/directory. Missing, invalid, unwritable or half-configured security material
fails startup rather than falling back to plaintext.

The SDK validates AES-GCM subject AAD. The logger reads encrypted
`E2E_KEYRING/current`, adopts and persists rotations, polls every 2 seconds, keeps
the previous key during the rotation window and drops it when the KV key is
removed. A missing KV bucket leaves the existing keyring untouched. NATS
permissions must allow these KV reads and response stream/consumer management.

## Tests (no production connections)

```sh
uv sync --locked
uv run --locked pytest -q
# Opt-in: needs access to a local Docker daemon. Starts isolated temporary
# containers with random loopback ports; removes only its own containers/network.
RUN_DOCKER_INTEGRATION=1 uv run --locked pytest tests/test_integration.py -q
# Native fallback: use checksum-verified official ClickHouse/NATS executables.
# All service ports are random loopback ports; data is disposable. No .env read.
RUN_NATIVE_INTEGRATION=1 \
  CLICKHOUSE_TEST_BINARY=/absolute/path/to/clickhouse \
  NATS_TEST_BINARY=/absolute/path/to/nats-server \
  uv run --locked pytest tests/test_integration.py -q
```

Unit tests use real loopback HTTP transport, real SDK AES-GCM/rotation and
controlled NATS boundaries. Integration exercises real ClickHouse/NATS, all six
subject shapes, command WorkQueue isolation, backend consumer independence,
nanosecond/raw-text preservation, old/new telemetry envelopes, additive DDL and
offline backfill, and response retry across a database failure. Both Limits and
Interest response retention are tested without changing the broker policy. The
native mode runs the same assertions, not a simulation; it does not verify the
Docker image/build/entrypoint. Use only downloaded, checksum-verified test
binaries, not a live service path/config. `pytest` temporary data defaults to
`TMPDIR`; native child processes are terminated by fixture cleanup.

References: [HTTP](https://clickhouse.com/docs/interfaces/http),
[JSONEachRow](https://clickhouse.com/docs/interfaces/formats/JSONEachRow),
[batch inserts](https://clickhouse.com/docs/optimize/bulk-inserts),
[DateTime64](https://clickhouse.com/docs/sql-reference/data-types/datetime64).
