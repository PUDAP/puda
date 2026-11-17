---
name: puda-protocol
description: Create, edit, validate, and run PUDA protocol JSON, including multi-machine steps, delays, and live command safety metadata. Use when planning or executing PUDA protocols.
---

# PUDA protocols

Create or update protocol JSON under the project's `protocols/` directory. Reuse existing protocols when appropriate; create a new file when requested or needed.

## Execution policy

- **Default:** create or reuse an appropriate protocol, validate it, then execute it with `puda protocol run`.
- **Manual-control exception:** use `puda machine start`, `puda machine run`, and `puda machine complete` (see **puda-manual-ui**) only when the operator specifically requests interactive manual control.
- Never use direct commands as a shortcut for routine execution or as a fallback after protocol failure; recover as described in [safety and execution](references/safety-and-execution.md#troubleshooting). Manual control must still honor advertised safety requirements and operator approval; failure does not authorize bypassing safety gates.
- Read-only discovery, state inspection, and telemetry watching require neither a protocol nor a manual run lifecycle.

## Workflow

1. Work from an initialized project (see **puda**).
2. Read [protocol format](references/format.md) for fields, IDs, timestamps, parallel steps, and CLI-only `wait` commands. Use the project UUID from `project.md`; generate a new protocol UUID and real UTC timestamp for a new protocol.
3. Discover machines with `puda machine list`; consult machine references and previous protocols. Fetch `puda machine commands <machine_id>` for every machine command used. Ask the user if the correct machine or command remains unclear. Do not look up `wait` on a machine.
4. Copy every advertised safety object unchanged. Follow its `requires` and `forbidden_when` conditions. Read [safety and execution](references/safety-and-execution.md) when handling safety metadata or running a protocol.
5. Write `protocols/<protocol_id>.json`. Unexecuted authoring is outside run-note scope; no `project.md` update is required for every file edit. Preserve existing project context and legacy history.
6. Run `puda protocol validate -f <file_name>`; success must be exactly `passed`. Fix errors and repeat validation.
7. When executing the protocol, honor confirmation gates. After execution, write a note (see below).

## Run context and notes

- Before continuing work, read `project.md` for goals, decisions, and legacy history; retrieve relevant runs' `steps`, `notes`, and command evidence through **puda-data**. Historical equipment observations never replace fresh live-state checks.
- From the intended project root, append an authored summary with `puda protocol note --run <run_id> --text '<summary>'`, using the actual run ID from execution output or stored records. After execution, including partial or failed runs, record intent, observed outcome, deviations, recovery/related run IDs, uncertainties, and real project-relative Markdown links to reports, plots, and logs. Distinguish observation from interpretation.
- `puda protocol note` requires CLI 0.1.6-rc1 or later and an existing protocol-associated run; it does not create one. The CLI timestamps and atomically appends the supplied text to `run.notes`; it does not write a narrative. Check returned JSON and read back notes to verify persistence. If saving fails, report it; do not claim success or silently duplicate the summary in `project.md`. Repeating the command appends again, so inspect notes before retrying an uncertain submission.
- Note timestamps are recording times, not execution times. `run.steps` stores the requested `--steps` selector, not proof of completion. For new unrestricted runs, `steps=NULL` means no selection was requested; legacy rows migrated with NULL have unknown selection. Use command logs to establish what ran.
- Keep project-level context and legacy history in `project.md`, updating durable context when it meaningfully changes. Do not automatically import, delete, or rewrite old history.

## Invariants

- Commands sharing a `step_number` run in parallel; never repeat a `machine_id` in that group.
- `wait` is handled by the CLI, never dispatched to hardware. Omit its `machine_id` for a protocol-wide pause; set it for a machine-specific pause.
- Safety metadata must match the live catalog, including all fields; refresh it after edits.
- At a `confirm: true` gate, show the operator the complete displayed commands and safety context, then wait for explicit approval before submitting `yes`. Parallel commands share one gate. Prompt only when the catalog sets `confirm: true`; reject or terminate if approval is denied.
