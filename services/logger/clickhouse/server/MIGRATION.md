# Non-destructive split-table migration

This procedure is operator-run, not automatic. `001-events.sql` stays unchanged;
`002-split-events.sql` only creates `puda.command_logs` and `puda.telemetry`.
No data is copied, renamed, deleted or dropped at logger startup. Fresh volumes
run both files; existing volumes **do not** rerun Docker init scripts.

## Cutover

1. Back up the legacy data and current logger/config. Inspect `SHOW CREATE TABLE
   puda.events`, `SELECT version()` and any pre-existing destination tables.
   `CREATE ... IF NOT EXISTS` is repeatable but does **not** reconcile incompatible
   tables. Resolve collisions before starting the new writer.
2. From `clickhouse/server`, create the new tables explicitly (credentials remain
   inside the container; use your approved operator context):

   ```sh
   docker compose exec -T clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery' < initdb/002-split-events.sql
   ```

   Grant the writer INSERT and SELECT on **both** new tables, not just events:

   ```sql
   GRANT INSERT, SELECT ON puda.command_logs TO puda_logger;
   GRANT INSERT, SELECT ON puda.telemetry TO puda_logger;
   DESCRIBE TABLE puda.command_logs;
   DESCRIBE TABLE puda.telemetry;
   ```

3. Drain/stop **every** old ClickHouse logger replica and record the cutover time
   and legacy counts. Leave its response durables/cursors intact. Freeze writes
   to `puda.events`; do not dual-run old and new writers sharing the same groups:
   they would load-balance rather than both receiving every message.
4. Remove `CLICKHOUSE_TABLE` from the logger environment. Set
   `CLICKHOUSE_COMMAND_TABLE=command_logs` and `CLICKHOUSE_TELEMETRY_TABLE=telemetry`.
   Validate with `--check-config`, then `--healthcheck`; start the new logger only
   after both grants/tables exist. Update dashboards to the separate tables.
5. Roll out the **dual-format consumers before the new SDK publishers**. The SDK
   now emits `{timestamp, data:{...}}` for health/streams only; older publishers
   still work. This logger, the Influx Python subscriber and the ReductStore health
   subscriber accept the envelope. Audit custom consumers and dashboards that
   extract top-level metrics. CLI watch/raw monitor consumers display the full
   JSON and need no field remapping. Heartbeat, state, commands, responses and
   subjects are unchanged. No published SDK release or dependency pin is changed
   by these local edits; arrange a reviewed SDK build/release separately.

Core command taps and telemetry are best-effort: the stopped interval can lose
data. Durable responses may replay pending messages, subject to broker retention;
Interest retention cannot recover messages from before a consumer existed. An
uncertain write or ACK can duplicate responses. No cutover can retroactively
recover lost Core traffic. Rollback stops the new logger first and restores the
old binary/config, retaining all three tables and both histories; review the gap
and response cursor before resuming. Do not reset consumers to force replay.

## Optional history backfill (isolated staging)

Leaving history in `puda.events` is safe. If unified history is needed, export the
**frozen** legacy table into a private file, convert offline, and insert into
**new, empty staging tables** first. This keeps historical duplicates and cannot
clobber live data. Example from `clickhouse/server`:

```sh
umask 077
# Capture counts and metadata separately in your migration ledger.
docker compose exec -T clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT * FROM puda.events FORMAT JSONEachRow"' > legacy-events.jsonl
(cd ../logger && uv run --locked python backfill.py ../server/legacy-events.jsonl ../server/history-batch-1)
```

The converter has **no network/environment loading**, reparses `raw_json` using
the same normalization as live ingestion, preserves original event/receipt
nanoseconds and fingerprints, and keeps all source rows (including identical
ones). Command metadata comes from the stored legacy columns. It refuses an
existing output directory; invalid rows abort and remove insertable outputs.
Inspect failures privately rather than logging payloads. Large exports are
streamed, but disk space is required for export plus both outputs. Unknown or
malformed historical rows require operator review; nothing is silently skipped.
The same exact-two-key envelope ambiguity described in the logger README also
applies to backfill; audit ambiguous legacy messages before converting.

Create staging tables with unique, ledger-recorded names. **If either name
already exists, stop and investigate instead of inserting again.**

```sql
CREATE TABLE puda.command_logs_history_1 AS puda.command_logs;
CREATE TABLE puda.telemetry_history_1 AS puda.telemetry;
```

```sh
docker compose exec -T clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "INSERT INTO puda.command_logs_history_1 FORMAT JSONEachRow"' < history-batch-1/command_logs.jsonl
docker compose exec -T clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "INSERT INTO puda.telemetry_history_1 FORMAT JSONEachRow"' < history-batch-1/telemetry.jsonl
```

Reconcile export count = converter counts = staging counts; compare raw text,
metadata, min/max event and receipt times, nulls, nested fields and representative
queries. Keep snapshots/export checksums and a per-file insert ledger. After
review, query a `UNION ALL` view over live + staging, for example:

```sql
CREATE VIEW puda.command_logs_all AS
SELECT * FROM puda.command_logs UNION ALL SELECT * FROM puda.command_logs_history_1;
CREATE VIEW puda.telemetry_all AS
SELECT * FROM puda.telemetry UNION ALL SELECT * FROM puda.telemetry_history_1;
```

Do not union these with `puda.events` too: that would count history twice. Keep
history separate until you have verified the cutover has no overlap. Do not
blindly deduplicate on `event_id`: it is a content fingerprint, not an event ID,
and identical legitimate telemetry samples must survive.

**Idempotency:** only the additive DDL is idempotent. MergeTree INSERT/backfill
and uncertain HTTP retries are **not** idempotent; rerunning an insert duplicates
rows. Two table inserts are not transactional. If an import partially fails,
mark the batch uncertain, reconcile its staging data and use a separately named
reviewed batch; do not blindly rerun, truncate, drop or delete the legacy table.
The output-directory guard prevents accidental regeneration, not duplicate
imports. No automatic migration, backfill or deployment was performed.
