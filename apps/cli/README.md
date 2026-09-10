# puda-cli

## Commands

Top-level order matches `puda --help` (alphabetical). Nested order matches each `puda <cmd> --help`. Global flags: `-h` / `--help`, `-v` / `--version`.

```
puda
├── completion               Generate the autocompletion script for the specified shell
├── config
│   ├── edit                 Edit PUDA CLI configuration
│   └── list                 List PUDA CLI configuration values
├── db
│   ├── exec [sql]           Execute SQL commands on the database
│   └── schema               Display the database schema
├── healthcheck              Check NATS server/cluster/gateway health [--nats-servers] [--gateway-servers] (JSON; --human for text)
├── help                     Help about any command
├── init [path]              Initialize a new PUDA project (requires --name)
├── login                    Log in to a PUDA account
├── logout                   Log out of a PUDA account
├── env                      NATS connection environments (bears, imre, ntu)
│   ├── current              Show the active env
│   ├── list                 List envs; * marks active
│   └── switch <env>         Set the active env
├── machine                  Optional: --nats-servers (overrides active env)
│   ├── commands <machine_id>  List commands the machine exposes [--command names] (JSON; --human for text)
│   ├── home <machine_id> [machine_id...]  Home machine(s)
│   ├── list                 Broadcast puda.cmd.ping and list pong responders with description and livestream_count (JSON; --human for text)
│   ├── ping <machine_ids>   Ping comma-separated machine IDs (JSON; --human for text)
│   ├── reset <machine_id>   Reset a machine
│   ├── state <machine_id>   Get the state of a machine as JSON
│   ├── update <machine_id>  Tell a PUDA edge to pull (git/docker) and restart
│   └── watch                Stream tlm/evt as NDJSON (requires --targets)
├── project
│   └── hash                 SHA-256 hash of project-linked DB rows (--id)
├── protocol
│   ├── run                  Run a protocol on machines via NATS
│   └── validate             Validate a protocol JSON file
├── skills                   Requires Node.js / npx
│   ├── install [repo...]    Add default + optional skill repos, then sync
│   └── update               Refresh installed skills (npx skills update)
├── update                   Upgrade or pin the puda CLI from GitHub releases
└── version                  Print the version information
```

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
