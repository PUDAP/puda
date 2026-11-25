# puda-cli

## Commands

Top-level order matches `puda --help` (alphabetical). Nested order matches each `puda <cmd> --help`. Global flags: `-h` / `--help`, `-v` / `--version`.

```
puda
├── completion               Generate the autocompletion script for the specified shell
├── config                   Manage user config
│   ├── edit                 Edit the user config file
│   ├── get <key>            Read user.user_id, user.username or user.default
│   ├── list                 List the user identity (user.default=true if derived from the OS)
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
├── login                    Set your username (replaces the default identity)
├── logout                   Clear your username; profiles are kept
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

## Edge protocol compatibility

Edges report `protocol_version` (`"MAJOR.MINOR"`) in every pong. This CLI
supports Edge Protocol 1.x; an edge that reports no `protocol_version` (Python
SDK before 0.1.0), another major or a malformed value is unsupported: update the
PUDA SDK on that machine. `sdk_version` is informational. `machine list` and
`machine info` print one stderr warning per unsupported responding edge without
changing stdout or exit status; `healthcheck` reports the result in its JSON
(see its machine contract below). CLI and SDK packages are versioned
independently; CLI 0.2.0 and Python SDK 0.1.0 are the first releases speaking
Edge Protocol 1.0. See [Edge protocol compatibility](docs/compatibility.md).

The `machine ping` alias has been removed; use `puda machine info <machine_ids>`.

## Healthcheck machine contract

`puda healthcheck` writes exactly one JSON object to stdout by default, including
unhealthy reports; `--human` renders the same checks as text. A completed report
has empty stderr: no separate edge-protocol advisory, redundant `Error: NATS
healthcheck ...`, or update notification. Exit code is 0 for NATS `status: "ok"`
and 1 for `degraded`/`unhealthy`. Edge protocol compatibility is advisory only and **never**
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
`supported_protocol` (`"1.x"`), and `machines` (an array, empty when not
checked). Its status is:

| `status` | `reason` | Meaning |
| --- | --- | --- |
| `not_checked` | `nats_unreachable` | No local server reachable; fleet discovery is skipped. See server errors. |
| `not_checked` | `no_responders` | Fresh discovery yielded no valid pongs (including silent subscriptions). |
| `not_checked` | `discovery_error` | Fresh discovery failed before any edge replied; `error` contains this distinct failure. |
| `supported`/`unsupported` | `discovery_incomplete` | Some edges replied before discovery reported `error`; `machines` lists them, but others may be missing. |
| `supported` | absent | Every unique responding edge speaks Edge Protocol 1.x. |
| `unsupported` | absent | At least one responding edge does not. |

Each `machines[]` entry has `machine_id`, the reported `sdk_version` and
`protocol_version` (empty if missing), and `status` (`supported`/`unsupported`).
Each unsupported edge also gets an advisory `sdk_unsupported` issue whose
`next_step` names the machine whose PUDA SDK to update.

Discovery uses only successfully probed local URLs and the active profile, with
`--timeout` as the fleet pong window (default 2s; also each server probe timeout).
It checks every unique valid live responder, never stored machine states; offline
or late edges are not certified. For example, after a transport failure the dependent fields include:

```json
{
  "jetstream": {"status": "not_checked", "reason": "nats_unreachable", "ok": false},
  "compatibility": {
    "status": "not_checked", "reason": "nats_unreachable",
    "advisory_only": true, "supported_protocol": "1.x", "machines": []
  }
}
```

This snippet shows only the dependent fields, not the complete report.

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

1. **Choose a username (optional)**
   ```bash
   puda login --username <name>
   ```
   Login is not required. Without it, the first command that needs an identity
   (for example `puda init`, `puda config list` or a machine command) stores a
   default identity in the global config: your OS username (Windows `DOMAIN\`
   prefix removed, unsupported characters replaced by `-`, `puda-user` if
   unavailable) plus a generated user ID, marked `user.default=true`. Later runs
   reuse it. `puda login` replaces the default username and keeps that user ID.
   No server is contacted. `puda logout` clears only the identity, keeping NATS
   profiles and other settings; the next command creates a new default identity
   with a new user ID. Neither command deletes an unreadable config file.

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

### Local skills (deployment monorepo)

Pass a local directory to symlink its skills instead of copying them, so edits
made through the agent stay in the source repository:

```bash
puda skills install ~/puda-<deployment>/skills
```

Any existing directory, or an argument starting with `./`, `../`, `/` or `~`, is
local. It can be one skill folder, a folder of skills, or a repository root with
`skills/`. Each skill is linked as `~/.agents/skills/<name>`, and from there into
`$HERMES_HOME/skills` (default `~/.hermes/skills`), `~/.claude/skills` and
`~/.cursor/skills` when those agents are installed. Each link is printed as
`symlinked <target> -> <source>`. Existing symlinks are replaced; a copied
folder with the same name is never deleted and makes the command exit non-zero
after the other skills are linked. Local paths never go through npx.

Upgrading the CLI and running `puda skills update` re-adds official skills from
the new release, replacing same-name legacy `PUDAP/skills` lock entries. It does
not remove legacy-only skills such as `puda-memory`. See the
[migration guide](docs/skills-migration.md) for lock/coexistence details,
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
