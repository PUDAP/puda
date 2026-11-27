# Edge Protocol 1.0 schema (fresh database)

Logger 1.0 speaks PUDA Edge Protocol 1.0 only and has no migration path from
0.0.x. `initdb/002-split-events.sql` creates the 1.0 schema, `puda.command_logs`
(with `protocol_version`) and `puda.telemetry`, on a **new** data volume. The
legacy `puda.events` table and the history backfill converter were removed.

- Existing volumes do not rerun init scripts, and `CREATE TABLE IF NOT EXISTS`
  does not alter a pre-1.0 `command_logs`. The logger's `--healthcheck`/startup
  check fails against such a table (missing `protocol_version`).
- To upgrade: stop every old logger replica, keep the old volume (or database)
  as read-only history, and start ClickHouse on a fresh volume, or create a new
  database from `002-split-events.sql` and set `CLICKHOUSE_DATABASE`. Then grant
  the writer `INSERT, SELECT` on both tables (see [README](README.md)).
- Old rows are not converted. 0.0.x telemetry (flattened) and commands
  (`header.version`/`command.version`) are not valid 1.0 messages; query the old
  history separately if needed.
- Never delete volumes to upgrade; back up before switching.
