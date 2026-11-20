# Skills

PUDA's agent skills live in the main `PUDAP/puda` repository as ordinary files in
`skills/`. They are versioned with CLI releases, not maintained as a nested Git
repository or submodule. See the [migration guide](../apps/cli/docs/skills-migration.md)
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

For example, a telemetry inspection loads `puda/SKILL.md` and `puda/references/profiles-and-telemetry.md`; it does not need camera, clock, or setup instructions. Run-note rules live in `puda-protocol`; run-data retrieval and analysis live in `puda-data`.

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

Run `puda --help` and `puda <command> --help` for the installed command tree and flags.

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

Both commands accept `--ref <git-reference>` to select a branch or tag (for example
`--ref main` or `--ref v0.1.6`). See the [migration guide](../apps/cli/docs/skills-migration.md#installation-policy)
for ref rules and [lock and coexistence precautions](../apps/cli/docs/skills-migration.md#coexistence-locks-and-migration-precautions).

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
