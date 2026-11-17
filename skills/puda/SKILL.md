---
name: puda
description: Set up PUDA CLI/projects/profiles and inspect machines, health, telemetry, cameras, and clocks.
---

# PUDA

Use this skill to prepare a PUDA project, select its connection profile, and inspect machines and telemetry. Protocol authoring and execution belong in **puda-protocol**; run-data retrieval and analysis belong in **puda-data**. The CLI and Python SDK are versioned independently.

Before operating machines, follow the execution policy in **puda-protocol** (protocol execution by default; manual control only when the operator requests it).

## Before operating

1. Check `puda --version` and relevant command `--help`; use the installed interface rather than assuming support.
2. Confirm the intended lab and active connection profile. Obtain broker settings and credentials from the user or deployment configuration; never assume them. User identity belongs to `puda config`, broker settings to `puda profile`, and project settings to `puda project config`.
3. For execution, locate the intended initialized project and work from its root. Initialize only when a project is genuinely missing; do not reinitialize an existing project to upgrade it. Read-only profile/machine inspection needs no project. Do not repeat login or setup when the environment already works.
4. Read `project.md` for goals, durable decisions, and legacy history. Retrieve relevant prior run notes, requested steps, and command evidence through **puda-data** before continuing an experiment. Historical equipment observations are not current state.
5. Discover the required machines, inspect fresh state, and fetch advertised commands. Resolve missing machines, stale state, or ambiguous targets before operation. Use protocol execution unless the task specifically needs manual control.

## Inspect machines

Use `puda machine --help` and `puda healthcheck --help` for commands and flags.

- Start with `puda healthcheck` when connectivity is in doubt. `compatibility` is advisory; to diagnose a failing report, use **puda-deployment**'s network and NATS reference.
- Run only the inspections the task needs, typically `machine info <id>` and `machine commands <id>` before authoring or running a protocol.
- Listed machines and stored state can be stale: check timestamps and responsiveness before assuming a machine is ready.
- Always give `machine watch` a bounded `--timeout`, and quote wildcard subjects.

## Task-specific references

Read only the reference needed for the task:

- **Installation, upgrades, login, project initialization, or skills:** [setup](references/setup.md).
- **Connection profiles and detailed telemetry inspection:** [CLI profiles and telemetry](references/cli-profiles-and-telemetry.md).
- **Clock synchronization:** [Chrony / NTP](references/chrony.md), with the [Linux](scripts/sync-clock.sh) or [Windows](scripts/sync-clock.ps1) helper. Obtain the site NTP IP first; configure Chrony on the host, not inside an edge container.
- **Camera streaming:** [livestream setup](references/livestream.md). Obtain camera, feed name, description, MediaMTX host, and target machine IDs before publishing video.

For additional documentation, consult https://docs.puda.co/llms.txt.

## Completion checks

- Verify the actual result or fresh observed state; command acceptance alone is not proof of completion.
- Report incomplete cleanup, stale observations, and unknown outcomes explicitly. Never repeat a physical operation just to obtain a cleaner log or repair a missing note.
- Write run summaries with `puda protocol note` as described in **puda-protocol**; keep project-level context and legacy history in `project.md` without deleting or automatically importing it.
