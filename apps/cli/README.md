# puda-cli

## Commands

Top-level order matches `puda --help` (alphabetical). Nested order matches each `puda <cmd> --help`. Global flags: `-h` / `--help`, `-v` / `--version`.

```
puda
├── completion               Generate the autocompletion script for the specified shell
├── config                   Manage user config
│   ├── edit                 Edit the user config file
│   ├── get <key>            Read user.user_id or user.username
│   ├── list                 List the logged-in user
│   └── set <key> <value>    Set user.user_id or user.username
├── db
│   ├── exec [sql]           Execute SQL commands on the database
│   └── schema               Display the database schema
├── encryption               Check or rotate payload encryption on an encrypted profile
│   ├── rotate               Install a new lab key
│   └── status               Show which edges have the current lab key
├── healthcheck              Check NATS server/cluster/gateway health (JSON; --human for text)
├── help                     Help about any command
├── init [path]              Initialize a new PUDA project (requires --name)
├── login                    Log in to a PUDA account
├── logout                   Log out of a PUDA account
├── machine                  Machine operations (JSON; --human for text)
│   ├── commands <machine_id>  List commands the machine exposes [--command names] (JSON; --human for text)
│   ├── home <machine_id> [machine_id...]  Home machine(s)
│   ├── list                 Broadcast puda.cmd.ping and list pong responders with description, livestream_count, and tlm_stream_count (JSON; --human for text)
│   ├── info <machine_ids>   Ping comma-separated machine IDs and show status, tlm_streams, and livestreams (JSON; --human for text)
│   ├── reset <machine_id>   Reset a machine
│   ├── state <machine_id>   Get the state of a machine as JSON
│   ├── update <machine_id>  Tell a PUDA edge to pull (git/docker) and restart
│   └── watch [subject...]   Stream NATS subjects as NDJSON (wildcards allowed; -m <ids> for whole machines)
├── profile                  Named NATS connections (JSON; --human for text)
│   ├── add <name>           Save a profile (--servers, optional --gateway-servers, --ca and --key together for e2e)
│   ├── current              Show the active profile
│   ├── list                 List profiles; * marks the active one in text output
│   ├── remove <name>        Delete a profile
│   ├── set <field> <value>  Change nats_servers, gateway_servers, ca, or key on the active profile
│   └── switch <name>        Select the active profile
├── project
│   ├── config               Manage project config (puda.config)
│   │   ├── edit             Edit puda.config
│   │   ├── get <key>        Read a project config value
│   │   ├── list             List project config
│   │   └── set <key> <value>  Set a project config value
│   └── hash                 SHA-256 hash of project-linked DB rows (--id)
├── protocol
│   ├── note                 Append a UTC-stamped note (--run, --text) to a protocol run
│   ├── run                  Run a protocol on machines via NATS
│   └── validate             Validate a protocol JSON file
├── skills                   Official PUDA skills for AI agents (requires Node.js / npx)
│   ├── install [repo...]    Install release-pinned official + optional skills [--ref <git-reference>]
│   └── update [repo...]     Re-add selected global sources; migrate legacy installs [--ref <git-reference>]
├── update                   Upgrade or pin the puda CLI from GitHub releases
└── version                  Print the version information
```

## CLI / Python SDK compatibility

`machine list`, `machine info`, and `healthcheck` check each responding edge's
existing `sdk_version` against the embedded repository-root `compatibility.json`.
For `machine list` and `machine info`, stable versions outside the supported range
warn on stderr; unknown/development reports remain unknown. These warnings never
change stdout or exit status or block execution. `healthcheck` instead includes
all compatibility outcomes in its report (see its machine contract below).
The root `compatibility` array contains inclusive CLI/SDK range rules:
CLI 0.0.0–0.0.36 with SDK 0.0.15–0.0.16 (user-declared legacy support, **not
runtime-tested**), and CLI 0.1.0–0.1.6 with SDK 0.0.17–0.0.22. Legacy lower bounds
come from retained published-history inventory, not an invented SDK start.
All bounds are inclusive and compared numerically; prereleases remain unknown.
No matching CLI rule or invalid/missing bounds means unknown. Overlapping valid
rules form a union, not an envelope filling SDK gaps. In-range stable versions
are silent. Ranges are declarations, not exhaustive qualification: unpublished
SDK 0.0.20 is implied, not tested, and 0.0.22 is a pending local artifact.
Encryption, telemetry consumers and hardware remain outside the bounded software
checks. See the
[historical matrix](../../docs/compatibility-history.md) and the
[compatibility policy and test evidence](../../docs/compatibility.md).

Source builds require the full checkout: the CLI uses the root Go module to
embed the one policy file without generated duplication. Released binaries
remain standalone.

The `machine ping` alias has been removed; use `puda machine info <machine_ids>`.

## Healthcheck machine contract

`puda healthcheck` writes exactly one JSON object to stdout by default, including
unhealthy reports; `--human` renders the same checks as text. A completed report
has empty stderr: no separate SDK compatibility advisory, redundant `Error: NATS
healthcheck ...`, or update notification. Exit code is 0 for NATS `status: "ok"`
and 1 for `degraded`/`unhealthy`. SDK compatibility is advisory only and **never**
changes that status or exit code. Configuration/pre-report errors and stdout write
failures still exit nonzero and print an error on stderr; do not assume their
stdout contains a complete report. Other commands retain their error behavior.

Existing `status`, `servers`, `cluster`, `jetstream`, and `gateways` fields remain.
Detailed transport errors (including TLS certificate causes) appear only in each
affected `servers[].error` (or gateway's `servers[].error`). Dependent local/remote
`jetstream` objects retain `ok` and add:

- `status: "ok"` for a successful account check;
- `status: "failed", reason: "jetstream_error"`, with `error`, for an attempted
  JetStream check that failed;
- `status: "not_checked", reason: "nats_unreachable", ok: false`, without `error`,
  when no configured server in that cluster is reachable. `ok: false` alone no
  longer distinguishes failure from not checked; use `status`.

The additive `compatibility` object always includes `advisory_only: true`,
`cli_version`, and `machines` (an array, empty when not checked). Its status is:

| `status` | `reason` | Meaning |
| --- | --- | --- |
| `not_checked` | `nats_unreachable` | No local server reachable; fleet discovery is skipped. See server errors. |
| `not_checked` | `no_responders` | Fresh discovery yielded no valid pongs (including silent subscriptions). |
| `not_checked` | `discovery_error` | Fresh discovery failed before any edge replied; `error` contains this distinct failure. |
| `supported`/`unsupported`/`unknown` | `discovery_incomplete` | Some edges replied before discovery reported `error`; `machines` lists them, but others may be missing. |
| `supported` | absent (or `discovery_incomplete`) | Every unique responding edge is declared supported. |
| `unsupported` | absent | At least one responding edge is outside the declared ranges. |
| `unknown` | absent | No unsupported edge, but at least one cannot be evaluated. |

Each `machines[]` entry has `machine_id`, the exact reported `sdk_version` (empty
if missing), `status` (`supported`/`unsupported`/`unknown`), and `supported_ranges`
(an array of inclusive `{min,max}` bounds from the shared evaluator, empty for
unknown policy). Aggregate precedence is unsupported, then unknown, then supported;
inspect all entries for a mixed fleet. No local pip metadata is used.

Discovery uses only successfully probed local URLs and the active profile, with
`--timeout` as the fleet pong window (default 2s; also each server probe timeout).
It checks every unique valid live responder, never stored machine states; offline
or late edges are not certified. Compatibility policy and SDK wire formats are
unchanged. For example, after a transport failure the dependent fields include:

```json
{
  "jetstream": {"status": "not_checked", "reason": "nats_unreachable", "ok": false},
  "compatibility": {
    "status": "not_checked", "reason": "nats_unreachable",
    "advisory_only": true, "cli_version": "dev", "machines": []
  }
}
```

This snippet shows only the dependent fields, not the complete report.

## Update compatibility preflight

`puda update` (latest, positional version, or `--version`) checks responding edges
before its existing confirmation and binary replacement. Unlike inspection
commands, it fetches `compatibility.json` from the **target release's exact tag,
pinned to its commit**, not the installed CLI's bundled policy. Metadata fetches
are bounded and never fall back to `main` or a local policy. Warnings identify
machine IDs, reported Python SDK versions and the target's inclusive supported SDK
range to upgrade/change to, distinguishing newly unsupported pairs from
existing out-of-range pairs. Missing metadata/versions, failed discovery and no
responders remain unknown/not checked. A two-second fleet response window cannot
certify offline or late edges.

This is advisory: prompts and `--yes` retain their existing behavior, warnings use
stderr, and no SDK or machine is modified. Already-latest and background notifier
checks do not preflight. Source metadata trusts GitHub/repository ownership, not
a signed binding to the release binary; see the
[policy and trust details](../../docs/compatibility.md#update-preflight).

## Protocol run context

`puda protocol run --file protocol.json --steps 2,4-6` saves the exact requested
selector in `run.steps` on the run created for execution. Omitting `--steps`
stores SQL `NULL`. This records requested scope, **not completed steps**;
consult command logs and measurements for execution evidence. Existing databases
are upgraded automatically and repeat-safely on connection, preserving their
rows. Historical runs receive `NULL` for both new columns; their earlier step
selection cannot be inferred from that value.

Append a summary to an existing protocol-associated run without contacting hardware:

```bash
puda protocol note --run <run-id> --text 'Measured Δ: [report](reports/result.md), [plot](plots/result.svg), [log](logs/run.txt), [data](exports/result.csv)'
puda db exec "SELECT run_id, protocol_id, created_at, steps, notes FROM run ORDER BY created_at DESC LIMIT 20"
```

Both `--run` and `--text` are required. Blank notes, unknown run IDs and standalone
machine runs are rejected. Notes retain whitespace, multiline text, Unicode and
Markdown links verbatim; linked files are not opened, copied or uploaded. Each
append adds `[UTC RFC3339 timestamp] text`, separated from previous notes by a
blank line. Concurrent appends are serialized by SQLite, with a five-second
lock wait; errors are reported rather than silently discarding notes. The JSON
response contains `run_id` and the complete saved `notes`, read back in the same
transaction. A deliberate repeat submission appends again (no deduplication).

Existing `puda db exec` queries (including `SELECT * FROM run`) expose both columns;
`puda db schema` also includes them. No separate history or artifact tables are used.

## Setup

After extracting the CLI, place the `puda` binary in your PATH (Linux: `~/.local/bin`, macOS: `/usr/local/bin` or `~/.local/bin`, Windows: `%USERPROFILE%\bin` or another folder already on your PATH).

Then run the following:

1. **Log in**
   ```bash
   puda login
   ```
   Enter your username when prompted.

2. **Install skills**
   ```bash
   puda skills install
   ```

## Skills sources and migration

`puda skills install` and `puda skills update` both install globally from
`https://github.com/PUDAP/puda/tree/v<VERSION>/skills`, using this binary's release
version. Streamlit is not installed or refreshed automatically. A leading
`v` in the binary version is handled without doubling it; release candidates
retain their suffix. Neither command invokes a blanket `npx skills update`.

Use `--ref <git-reference>` to select a branch or tag, for example `--ref main`
or `--ref v0.1.6`. Explicit refs are passed literally (no automatic `v` prefix).
Use simple names starting with a letter or digit, followed by letters, digits,
dots, underscores or hyphens; slashes, `..`, trailing dots and `.lock` are rejected.
Development/snapshot/pseudo-version binaries require an explicit ref; missing release tags or
skills subtrees fail without falling back to main. Custom sources are passed
unchanged after the defaults: `puda skills update owner/custom#stable`.
Unspecified custom skills and project-local installs are left alone. To opt into
Streamlit explicitly, use `puda skills install streamlit/agent-skills` or
`puda skills update streamlit/agent-skills`. Existing Streamlit skills are not removed.

Upgrading the CLI and running `puda skills update` re-adds official skills from
the new release, replacing same-name legacy `PUDAP/skills` lock entries. It does
not remove legacy-only skills such as `puda-memory`. See the
[migration guide](../../docs/skills-migration.md) for lock/coexistence details,
local testing before publication, and the old-repository pointer plan.

## Build and release

From `apps/cli`. Requires [just](https://github.com/casey/just). Publish also requires [goreleaser](https://goreleaser.com/install/) and a GitHub token that can create releases (`GITHUB_TOKEN` or `gh auth`).

```bash
just build              # ./puda
just install            # GOPATH/bin
just publish-snapshot   # dry-run, no GitHub release
```

Release (tag the git repo, then publish from this directory). Paste AI-generated notes into the heredoc; omit it to let goreleaser write notes from commits:

```bash
git tag -a v0.0.37 -m "v0.0.37"
git push origin v0.0.37
just publish <<'EOF'
## Breaking Changes
- ...

## Changes
- ...
EOF
```

## Troubleshooting

### Windows Issues

If you see **"Python was not found"** when running `puda.exe`, the executable is using Windows PATH and not finding your Python. Use the method below.

**Option 1 – One-off (current session)**  
Prepend your Python directory to PATH, then run puda:

```powershell
$env:PATH = "C:\Python313;$env:PATH"
.\puda.exe
```

Use the folder where your `python.exe` lives (e.g. `C:\Python313` if `which python` is `/c/Python313/python`).


**If you see "Python was not found" (Microsoft Store message)**  
Disable the Store aliases: **Settings** → **Apps** → **Advanced app settings** → **App execution aliases** → turn **Off** for `python.exe` and `python3.exe`.

**If you see `exec: "python3": executable file not found in %PATH%`**  
`puda.exe` looks for **`python3`**; on Windows the installer often only provides `python.exe`.

- **Option :** Create a copy in your Python folder (run PowerShell **as Administrator**):  
  `Copy-Item "C:\Python313\python.exe" "C:\Python313\python3.exe"` 
