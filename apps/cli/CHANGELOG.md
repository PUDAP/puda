# PUDA CLI changelog

## Unreleased

### Added

- `puda machine commands` reports the lifecycle hooks the driver implements (`hooks` in JSON, a "Lifecycle hooks" line with `--human`), so agents can tell whether `estop` or `abort` reaches the hardware. `puda protocol validate` and `run` reject `start`, `complete` and hook names as steps with an explanation instead of "not found".
- `puda machine complete --abort` stops the running command instead of being refused, then ends the run (requires Python SDK 0.1.0 edges). Results now include the edge's `code` and `data` for every immediate command, so a refused `complete` reports `code: EXECUTION_LOCKED` with `data.running` (name, step, elapsed) and `data.queued`, and an abort reports `data.aborted`, `driver_abort` and `queued`. An abort returns at once; the running command is answered `COMMAND_CANCELLED` when its driver call returns, and the machine runs nothing else until then.

### Changed

- **Breaking:** the envelope header field `version` is renamed `protocol_version` and is required: edges refuse a command whose `header.protocol_version` is missing or not `1.x`. `command.version` is removed from command envelopes and from protocol files (a leftover `"version"` key in a protocol step is ignored).
- Edge compatibility is judged by the pong's `protocol_version` (`"MAJOR.MINOR"`) instead of CLI/SDK version ranges. This CLI supports Edge Protocol 1.x; a missing value (Python SDK before 0.1.0), another major or a malformed value is unsupported. `machine list`/`info` warn on stderr with `warning: machine <id> speaks edge protocol <v|none>; this CLI supports 1.x (update the edge's PUDA SDK)`, and `machine info` reports `protocol_version`. The `healthcheck` `compatibility` section reports `supported_protocol: "1.x"` and per machine `machine_id`, `sdk_version`, `protocol_version` and `status` (`supported`/`unsupported`); the `unknown` state, `cli_version` and `supported_ranges` are gone. See `apps/cli/docs/compatibility.md`.
- Interrupting `puda protocol run` (Ctrl+C, SIGTERM) now sends `complete --abort` to every started machine, so commands still running on the edges are stopped instead of continuing unobserved. A normal finish or a failed step still sends plain `complete`.
- Immediate commands (`start`, `complete`, `pause`, `resume`, `reset`, `estop`) use core NATS request/reply on `puda.<id>.cmd.immediate` instead of the `COMMAND_IMMEDIATE` stream (edges need the matching Python SDK). An offline machine fails at once with `no responders: machine offline`; a missing reply fails with `no reply within Ns; outcome unknown`, and immediate commands are safe to retry.

### Removed

- The unused `cancel` immediate command constant. Use `puda machine complete --abort`.
- `compatibility.json`, the root Go module that embedded it and the version-range checks, replaced by `protocol_version`. Source builds no longer need the repository root.
- `puda update` no longer runs a Python SDK preflight against edges before replacing the binary; run `puda healthcheck` afterwards.

### Fixed

- `puda machine info` and the immediate lifecycle commands that ping first (`start`, `complete`, `reset`, ...) no longer report online machines as `invalid pong response`. A direct ping now reads every reply until a valid pong arrives or the timeout expires, so another subscriber on `puda.<id>.cmd.*` (such as a service answering `-NAK`) answering first is ignored. Remote edges (for example over Tailscale) were affected most because they always lose that race. If only non-pong replies arrive, the error reads `invalid pong response: no valid pong before timeout (ignored N non-pong replies)`.

## 0.1.7-rc1 — 2026-11-20 (prerelease)

### Added

- `puda healthcheck` checks the PUDA JetStream resources, not just that JetStream answers. The new `puda` section reports each stream and KV bucket (status, replicas, leader, lagging replicas, consumers). Required resources that are missing, leaderless or below quorum make the report `unhealthy` (exit 1); a single replica in a cluster or a lagging replica is `degraded`. A broker with JetStream but no PUDA streams was previously `ok`.
- `puda healthcheck` adds a top-level `issues` list. Each issue has `code`, `severity` (`unhealthy`, `degraded` or `advisory`), `target`, `source` (JSON path to the evidence; error text is not duplicated) and a concrete `next_step`, such as the exact `setup_streams.sh` command with the right `NATS_URL` and `REPLICAS`. Every non-ok status has a matching issue, and one cause affecting several resources is one issue. `--human` prints the issues first.
- Lost JetStream quorum is reported as `jetstream_no_quorum` / `puda_resource_no_quorum`, including the window after nodes stop while an old leader still claims leadership.

### Fixed

- `puda healthcheck` no longer conflates endpoints with brokers. `--human` prints `endpoints: N/M reachable` and `unique brokers responding: K`, counting distinct non-empty server IDs from successful probes (never names or URLs), shows each endpoint's server `id`, notes endpoints that reported no ID instead of grouping them, and prints `cluster: <name>` only for a real cluster, without the advertised-address count (that list stays in JSON `cluster.discovered`; advertised addresses prove neither identity nor cluster size). JSON keeps every existing field and adds `cluster.brokers` / `gateways[].brokers`, each broker's server `id`, `name` and the `endpoints` that reached it (plus `unidentified_endpoints` when non-zero).

## 0.1.6 — 2026-11-19

### Added

- `puda machine estop <machine_ids>` sends the new `estop` immediate command to every listed machine in parallel, without a ping or confirmation, and reports JSON results. Edges with Python SDK 0.0.23+ run the driver's `estop` command on a dedicated thread, cancel the running queued command, end the active run and latch the machine in state `estopped` until `puda machine reset` succeeds. `ESTOP_NOT_SUPPORTED` means the driver has no `estop` command and no hardware stop was sent; older SDKs answer "Unknown immediate command: estop". `compatibility.json` extends the CLI 0.1.x rule to SDK 0.0.23.
- `puda skills install <path>` and `puda skills update <path>` symlink skills from a local directory instead of copying them through npx, so edits stay in the source repository (for example a deployment monorepo's `skills/`). A path may be one skill folder, a folder of skills, or a repository root with `skills/`. Skills are linked as `~/.agents/skills/<name>` and into the skills directories of installed Hermes (`$HERMES_HOME`), Claude Code and Cursor; every link is printed as `symlinked <target> -> <source>`. Existing symlinks are replaced; copied folders with the same name are kept and reported with a non-zero exit. Missing path-like arguments and folders without skills fail before anything is installed.

### Changed

- `puda healthcheck` now emits exactly one JSON report for agents. SDK compatibility is included as an advisory `compatibility` object (`supported`/`unsupported`/`unknown`, or `not_checked` with `nats_unreachable`, `no_responders` or `discovery_error`; `discovery_incomplete` when some edges replied before an error), listed after `gateways`. Transport errors appear once, on the affected server; dependent JetStream checks report `status`/`reason` (`not_checked` vs `failed`), and JetStream or discovery permission denials are captured in the report instead of leaking to stderr. Unhealthy reports still exit 1 but no longer print a redundant `Error: NATS healthcheck …` line or compatibility prose on stderr. Configuration and output errors remain visible.
- Login is no longer required. Commands that need an identity (`init`, machine commands, protocol runs, `config`) create and persist a default identity in the global config when none exists: the sanitized OS username plus a generated user ID, marked `"default": true`. Later runs reuse it. `puda config list` prints `user.default=<bool>`; `puda config get user.default` reads it.
- `puda login --username <name>` replaces a default identity, keeping its user ID, and no longer prints simulated authentication-service messages. An explicit login still reports "already logged in". `config set user.username` also clears the default marker.
- `puda logout` clears only the user identity; NATS profiles, CA/key paths and other settings are kept. With no explicit login it reports "You are not logged in." and changes nothing. The next command creates a new default identity with a new user ID.
- Unreadable or unparseable global config files are no longer deleted by `login`; commands return an error and leave the file unchanged. Global config writes are atomic (temp file + rename, mode 0600).

### Fixed

- `puda init --help` now says it scaffolds `puda.config` (not `config.json`), matching the files actually created.

## 0.1.6-rc1 — 2026-11-17 (prerelease)

### Added

- `puda update` now performs a nonblocking Python SDK compatibility preflight before confirmation/replacement. Target policy comes from the exact resolved release tag's root `compatibility.json`, pinned to its commit via the existing fixed GitHub repository; bounded metadata failures never fall back to `main` or the installed map. Fresh live pongs identify affected machine IDs, reported SDK versions and target-supported upgrade/change choices, separating newly unsupported from existing out-of-range pairs. Unknown/dev versions, absent metadata/configuration, failed discovery and no responders remain unknown/not checked. Existing prompts, `--yes`, stdout and binary checksum/replacement behavior are unchanged; already-latest/background notifier checks do not ping edges. Shared pure policy evaluation, advisory formatting and fleet discovery are reused by list/info, healthcheck and update. See `apps/cli/docs/compatibility.md` for source trust and offline/late-edge limitations.

- Repository-root `compatibility.json` uses one `compatibility` array of inclusive CLI/`python_sdk` min/max rules: legacy CLI 0.0.0–0.0.36 with SDK 0.0.15–0.0.16 (user-declared, not runtime-tested), and modern CLI 0.1.0–0.1.6 with SDK 0.0.17–0.0.22. Both lower legacy bounds scope retained published history. Shared inspection/update evaluation compares stable versions numerically, unions matching rules, and leaves unmatched CLI versions, invalid bounds and prerelease/dev reports unknown. Range declaration is distinct from artifact qualification; unpublished SDK 0.0.20 is implied, not tested.
- `machine list`, `machine info`, and `healthcheck` emit nonblocking stderr advisories using the running edge's existing pong `sdk_version`, never local pip packages. Out-of-range stable versions have undeclared support; unknown/development/malformed versions, invalid rules and unmatched CLI versions report compatibility unknown. Stdout JSON, exit status, existing safety gates, and SDK wire formats are unchanged. No per-edge compatibility warning for nonresponders, and no compatibility-policy network fetch. Healthcheck adds a fresh bounded fleet ping and reports no responses or discovery errors as not checked on stderr, without changing NATS health status. See `apps/cli/docs/compatibility.md` for scope, isolated test evidence, and remaining qualification gates.

- `puda protocol note --run <run-id> --text <summary>` appends agent/operator context to an existing protocol-associated run. Notes receive a UTC recording timestamp; multiline text and Markdown links to reports, plots, logs, and exported data are preserved. The command returns JSON with `run_id` and the saved `notes`.
- `run.steps` stores the requested `--steps` expression verbatim. Newly recorded unrestricted runs use NULL. This is requested selection, not proof that commands completed; inspect command logs for actual execution.
- `run.notes` stores appended summaries. Concurrent append operations are atomic. Repeating a successful submission appends another note; inspect saved notes before retrying after an uncertain result.

### Skills source migration

- Seven PUDA agent skills now ship as ordinary files in `PUDAP/puda/skills`, aligned to the CLI release tag instead of the separate `PUDAP/skills` repository.
- `puda skills install` and `update` re-add this release's subtree; `--ref main` or `--ref v0.1.6` explicitly selects a simple branch/tag. Development binaries require an explicit ref, and missing tags fail without fallback.
- No automatic Streamlit installation or blanket update of unrelated skills. Same-name global skills replace the old source; back up customizations first. Legacy-only skills and project-local installs remain unchanged. See `apps/cli/docs/skills-migration.md`.

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
