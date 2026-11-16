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
| [puda-manual-ui](puda-manual-ui/SKILL.md) | Streamlit operator dashboards using CLI manual sessions. |
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
├── protocol
│   ├── run                  Run a protocol on machines via NATS
│   └── validate             Validate a protocol JSON file
├── machine
│   ├── list                 Discover machines via ping (description, livestream_count)
│   ├── state <machine_id>   Get the state of a machine
│   ├── reset <machine_id>   Reset a machine
│   └── commands <machine_id> Show available commands
├── livestream
│   ├── add                  Register host + stream name and attach machines
│   ├── list                 List fleet livestreams [--hosts] [--machines]
│   ├── rm                   Remove a livestream
│   ├── attach               Attach machines to a livestream
│   └── detach               Detach machines from a livestream
├── login                    Log in to a PUDA account
├── logout                   Log out of a PUDA account
├── config
│   ├── list                 List configuration values
│   └── edit                 Edit configuration in default editor
├── init [path]              Initialize a new PUDA project
├── skills
│   ├── install              Install agent skills
│   └── update               Update agent skills
└── db
    ├── exec [sql]           Execute SQL queries on the database
    └── schema               Display the database schema
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
