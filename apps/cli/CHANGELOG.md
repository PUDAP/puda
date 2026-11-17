# PUDA CLI changelog

## Unreleased

### Changed

- `puda healthcheck` now emits exactly one JSON report for agents. SDK compatibility is included as an advisory `compatibility` object (`supported`/`unsupported`/`unknown`, or `not_checked` with `nats_unreachable`, `no_responders` or `discovery_error`; `discovery_incomplete` when some edges replied before an error), listed after `gateways`. Transport errors appear once, on the affected server; dependent JetStream checks report `status`/`reason` (`not_checked` vs `failed`), and JetStream or discovery permission denials are captured in the report instead of leaking to stderr. Unhealthy reports still exit 1 but no longer print a redundant `Error: NATS healthcheck …` line or compatibility prose on stderr. Configuration and output errors remain visible.

## 0.1.6 — 2026-11-16

### Added

- `puda update` now performs a nonblocking Python SDK compatibility preflight before confirmation/replacement. Target policy comes from the exact resolved release tag's root `compatibility.json`, pinned to its commit via the existing fixed GitHub repository; bounded metadata failures never fall back to `main` or the installed map. Fresh live pongs identify affected machine IDs, reported SDK versions and target-supported upgrade/change choices, separating newly unsupported from existing out-of-range pairs. Unknown/dev versions, absent metadata/configuration, failed discovery and no responders remain unknown/not checked. Existing prompts, `--yes`, stdout and binary checksum/replacement behavior are unchanged; already-latest/background notifier checks do not ping edges. Shared pure policy evaluation, advisory formatting and fleet discovery are reused by list/info, healthcheck and update. See `docs/compatibility.md` for source trust and offline/late-edge limitations.

- Repository-root `compatibility.json` uses one `compatibility` array of inclusive CLI/`python_sdk` min/max rules: legacy CLI 0.0.0–0.0.36 with SDK 0.0.15–0.0.16 (user-declared, not runtime-tested), and modern CLI 0.1.0–0.1.6 with SDK 0.0.17–0.0.22. Both lower legacy bounds scope retained published history. Shared inspection/update evaluation compares stable versions numerically, unions matching rules, and leaves unmatched CLI versions, invalid bounds and prerelease/dev reports unknown. Range declaration is distinct from artifact qualification; unpublished SDK 0.0.20 is implied, not tested.
- `machine list`, `machine info`, and `healthcheck` emit nonblocking stderr advisories using the running edge's existing pong `sdk_version`, never local pip packages. Out-of-range stable versions have undeclared support; unknown/development/malformed versions, invalid rules and unmatched CLI versions report compatibility unknown. Stdout JSON, exit status, existing safety gates, and SDK wire formats are unchanged. No per-edge compatibility warning for nonresponders, and no compatibility-policy network fetch. Healthcheck adds a fresh bounded fleet ping and reports no responses or discovery errors as not checked on stderr, without changing NATS health status. See `docs/compatibility.md` for scope, isolated test evidence, and remaining qualification gates.

- `puda protocol note --run <run-id> --text <summary>` appends agent/operator context to an existing protocol-associated run. Notes receive a UTC recording timestamp; multiline text and Markdown links to reports, plots, logs, and exported data are preserved. The command returns JSON with `run_id` and the saved `notes`.
- `run.steps` stores the requested `--steps` expression verbatim. Newly recorded unrestricted runs use NULL. This is requested selection, not proof that commands completed; inspect command logs for actual execution.
- `run.notes` stores appended summaries. Concurrent append operations are atomic. Repeating a successful submission appends another note; inspect saved notes before retrying after an uncertain result.

### Skills source migration

- Seven PUDA agent skills now ship as ordinary files in `PUDAP/puda/skills`, aligned to the CLI release tag instead of the separate `PUDAP/skills` repository.
- `puda skills install` and `update` re-add this release's subtree; `--ref main` or `--ref v0.1.6` explicitly selects a simple branch/tag. Development binaries require an explicit ref, and missing tags fail without fallback.
- No automatic Streamlit installation or blanket update of unrelated skills. Same-name global skills replace the old source; back up customizations first. Legacy-only skills and project-local installs remain unchanged. See `docs/skills-migration.md`.

### Removed

- Removed the `machine ping` CLI alias. Use `machine info <machine_ids>` instead. Core NATS ping/pong transport remains unchanged, including fleet discovery.

### Compatibility and agent migration: 0.1.5 → 0.1.6

This CLI schema change is additive and non-breaking for existing named-column queries and records. No new tables, destructive migrations, or automatic Markdown imports are introduced. `SELECT * FROM run` now returns two additional nullable columns; positional consumers must use explicit column names.

1. Finish active protocol operations and stop all database writers for the full backup, migration, and readback window. Preserve the current configuration and old CLI binary. Locate the actual database using the project's configured database path (normally `puda.db`). Back it up with SQLite's backup facility, not a blind copy of a database with active WAL writers. For the default path, a one-time backup can be made with Python:

   ```python
   import sqlite3
   from pathlib import Path

   source = Path("puda.db")
   backup = Path("puda.db.before-0.1.6")
   if not source.is_file():
       raise SystemExit("Project database not found; check the configured path")
   with backup.open("xb"):
       pass  # Refuse to overwrite an existing backup.
   with sqlite3.connect(source) as src, sqlite3.connect(backup) as dst:
       src.backup(dst)
   ```

2. Install CLI 0.1.6 and check `puda --version`. From the intended project root, run:

   ```sh
   puda db exec "SELECT name, type FROM pragma_table_info('run') WHERE name IN ('steps', 'notes') ORDER BY name"
   ```

   Opening the database through the CLI automatically adds missing `steps TEXT` and `notes TEXT` columns in a transaction. The migration checks each column and is safe to repeat, including partially upgraded databases. This query triggers migration and verifies the persisted schema. `puda db schema` prints the bundled schema; it is not proof that an existing database has been migrated.

3. Verify existing records and retrieve new context using named columns:

   ```sh
   puda db exec "SELECT run_id, protocol_id, created_at, steps, notes FROM run ORDER BY created_at DESC LIMIT 20"
   ```

   Historical rows retain their original values and receive NULL in added columns. Historical NULL `steps` means the selection was not recorded, not proof that the full protocol ran. Do not rerun experiments to populate missing metadata.

4. Agents should save new run summaries with `puda protocol note`, including project-relative artifact links. The CLI saves text; it does not generate an interpretation. Read run notes and command logs before continuing or analyzing experiments. Notes' appended timestamps are recording times, not execution times; `run.created_at` remains unchanged.

5. Preserve existing `project.md` files and linked artifacts. Use `project.md` for project goals, durable decisions, and legacy history; new run summaries belong in the database. Unexecuted protocol authoring and project-level observations are not protocol-run notes. No migration deletes or rewrites Markdown.

Do not run `puda init` to upgrade an existing project. Do not manually execute ALTER statements through `puda db exec` (it accepts queries only). Existing SDK/NATS message formats and execution safety gates are not changed by this CLI feature.

### Separate SDK release

Python SDK 0.0.22 remains a separate, pending release and is not published by this CLI release. Its planned telemetry health/stream wire envelope `{timestamp, data}` is a separate consumer-facing breaking change, not a requirement of this SQLite migration. Upgrade telemetry consumers to accept both formats before deploying those SDK publishers. CLI 0.1.6 does not change SDK source or publish an SDK package.
