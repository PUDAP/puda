# Skills

PUDA's agent skills live in the main `PUDAP/puda` repository as ordinary files in
`skills/`. They are versioned with CLI releases, not maintained as a nested Git
repository or submodule. See the [migration guide](../docs/skills-migration.md)
for migration from the separate `PUDAP/skills` repository.

## Overview

This subtree contains skills for the Puda project, following the [Agent Skills](https://agentskills.io) standard. Each skill lives in its own directory with a required `SKILL.md` (YAML frontmatter + markdown body) and optional `references/`, `scripts/`, or `assets/`.

### Skill modules

| Skill | Description |
|-------|-------------|
| [puda](puda/SKILL.md) | CLI/project setup, profiles, machine inspection, telemetry, clocks, and cameras. |
| [puda-protocol](puda-protocol/SKILL.md) | Protocol creation, validation, execution, and command safety. |
| [puda-database](puda-database/SKILL.md) | Schema inspection and SQL through the PUDA CLI. |
| [puda-data](puda-data/SKILL.md) | Extraction, analysis, provenance hashes, exports, plots, experiment reports, and device adapters. |
| [puda-edge](puda-edge/SKILL.md) | Python SDK/API or GUI edge drivers and remote updates. |
| [puda-manual-ui](puda-manual-ui/SKILL.md) | Manual-control operator UIs (any framework) driving CLI start/run/complete, with livestreams from machine info. |
| [puda-deployment](puda-deployment/SKILL.md) | Host-to-labware commissioning, troubleshooting, and deployment records. |

### Progressive discovery

The [Agent Skills specification](https://agentskills.io/specification) separates discovery from task instructions and supporting resources:

1. At startup, a compatible agent reads only each skill's `name` and `description`.
2. When a task matches, it reads that skill's `SKILL.md` for the workflow, essential constraints, and resource links.
3. It reads only the linked references needed for the current operation, or executes the relevant bundled scripts. Do not preload every reference or every skill.

For example, a telemetry inspection loads `puda/SKILL.md` and `puda/references/cli-profiles-and-telemetry.md`; it does not need camera, clock, or setup instructions. Run-note recording lives in `puda-protocol`; retrieval and analysis notes live in `puda-data`.

Skill packaging enables this loading pattern; the agent client controls what it actually loads. Keep descriptions concise, keep detailed examples and task-specific procedures in focused references, and link those references directly from `SKILL.md`. Preserve safety and lifecycle constraints in the entrypoint. Keep entrypoints below the specification's recommended 500 lines / 5,000 tokens.

### Validate skill packages

Use the specification's reference validator (requires [uv](https://docs.astral.sh/uv/)):

```bash
uv tool install 'git+https://github.com/agentskills/agentskills.git#subdirectory=skills-ref'
for skill in */SKILL.md; do
  skills-ref validate "${skill%/SKILL.md}" || exit 1
done
```

Also check that relative resource links resolve and that each reference can be selected from its entrypoint without loading unrelated guides. The validator checks format, not instruction quality.

## CLI Reference

```
puda
├── config                   User identity (not broker settings)
│   ├── edit                 Edit the user config file
│   ├── get <key>            Read user.user_id, user.username or user.default
│   ├── list                 Print user.user_id, user.username, user.default
│   └── set <key> <value>    Set user.user_id or user.username
├── db
│   ├── exec [sql]           Execute SQL on the project database (JSON)
│   └── schema               Display the database schema
├── encryption               Encrypted (tls:// + key) profiles only
│   ├── rotate               Install a new lab key [--yes] [--retire]
│   └── status               Show which edges have the current lab key
├── healthcheck              One JSON NATS/JetStream health report [--timeout] [--human]
├── init [path]              Initialize a project (--name required, --description)
├── livestream               Fleet camera registry (JSON; --human)
│   ├── add                  --name --host [--description] [--machines]
│   ├── attach <name>        --machines
│   ├── detach <name>        --machines
│   ├── list                 [--hosts] [--machines]
│   └── rm <name>            Remove a livestream
├── login                    Set your username [-u/--username]; optional
├── logout                   Clear your username; profiles are kept
├── machine                  Machine operations (JSON; --human; -y/--yes)
│   ├── commands <machine_id>       Advertised commands [--command names]
│   ├── complete <machine_ids>      Complete a run [--run-id]
│   ├── home <machine_id...>        Home machine(s)
│   ├── info <machine_ids>          Status, tlm_streams, livestreams [--timeout]
│   ├── list                        Discover responsive machines [--timeout]
│   ├── pause|resume|reset <machine_ids>
│   ├── run <machine_id> <command> [params_json]  [--params] [--kwargs] [--run-id]
│   ├── start <machine_ids>         Start a run [--run-id]
│   ├── state [machine_id...]       State snapshot (all online if omitted) [--offline]
│   ├── update <machine_id>         Edge pull + restart [--source-type] [--ref]
│   └── watch [subject...]          NDJSON stream [-m ids] [--timeout] [--include-heartbeat]
├── profile                  Named NATS connections (JSON; --human)
│   ├── add <name>           --servers [--gateway-servers] [--ca --key]
│   ├── current | list
│   ├── remove <name>
│   ├── set <field> <value>  nats_servers, gateway_servers, ca or key
│   └── switch <name>
├── project
│   ├── config               edit | get <key> | list | set <key> <value> (puda.config)
│   └── hash                 --id <project_id> [--db]
├── protocol
│   ├── note                 --run <run_id> --text <note>
│   ├── run                  -f/--file [--steps] [-y/--yes]
│   └── validate             -f/--file
├── skills
│   ├── install [repo...]    [--ref]
│   └── update [repo...]     [--ref]
├── update [version]         Install a CLI release [--version] [-y/--yes]
├── version                  Print version information
└── completion               Shell completion script
```

## Installing skills with the PUDA CLI

These commands install globally; they do not require `puda init`. With a released
CLI containing the migration, the default official source is the main repository's
`skills/` subtree pinned to that CLI's release tag. Streamlit is not installed or
refreshed automatically; existing installations are not removed. To opt in, pass
`streamlit/agent-skills` explicitly to either command.

**Install** — first-time setup or re-add the selected sources:

```bash
puda skills install
```

**Update** — re-add release-matched skills after upgrading the CLI, including
migration of same-name global skills from the old repository:

```bash
puda skills update
```

Both commands accept `--ref <git-reference>` to select a branch or tag, such as
`--ref main` for remote development skills or `--ref v0.1.6` for a release. Refs
are literal (no added `v`), start with a letter or digit, and contain only letters,
digits, dots, underscores or hyphens. Empty refs, slashes, `..`, trailing dots and
`.lock` are rejected. Development binaries require an explicit ref; unavailable release tags/subtrees fail
without fallback. Optional custom repositories are passed unchanged after the
defaults. No blanket `npx skills update` runs. Legacy-only skills (including
`puda-memory`) and project-local installs are not removed automatically; see the
[lock and coexistence precautions](../docs/skills-migration.md#coexistence-locks-and-migration-precautions).

## Developing and testing skills

To try skills from a branch or a local clone before they land on `main`, use the CLI (`npx skills add`).

**Remote main** — requires the subtree to have been published:

```bash
npx skills add https://github.com/PUDAP/puda/tree/main/skills -y -g
```

**Local directory** — path to a skills repo checkout or any folder that contains skill packages (each with a `SKILL.md`):

```bash
npx skills add ./skills -y -g
```

## References

- [vercel-labs/skills](https://github.com/vercel-labs/skills)
- [skills.sh](https://skills.sh/)
- [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills)
