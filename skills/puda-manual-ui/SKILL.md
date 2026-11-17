---
name: puda-manual-ui
description: Build PUDA manual-control operator UIs in any framework that drive Start, Run, and Complete through the PUDA CLI, with optional jogging controls and livestreams.
---

# PUDA manual UI

Build operator UIs backed by subprocess calls to the PUDA CLI. Any UI framework is acceptable; use the user's or project's choice. Streamlit is one option, not a requirement.

## Workflow and references

1. Read [session lifecycle and CLI dispatch](references/session-and-dispatch.md) before implementing or changing controls. It defines the Start/Run/Complete lifecycle, CLI arguments, and errors.
2. For camera video, layout, or deployed URLs, read [layout and livestream](references/layout-and-livestream.md).
3. Before reporting completion, follow [the verification checks](references/verification.md).

## Invariants

- The UI must drive `puda machine start`, `puda machine run`, and `puda machine complete`. Machine actions and Complete require a successful Start.
- Run CLI calls from the PUDA project root, using the same machine set and hard-coded `--run-id manual` for Start, Complete, and actions. Change session state only after successful lifecycle calls.
- Dispatch every action with `puda machine run <machine_id> <command_name> --params '<json-object>' --run-id manual`, with captured output and a per-command timeout.
- Do not dispatch actions through temporary protocols, `puda protocol run`, a custom publisher, or a parallel NATS client.
- Show command, exit code, stdout, and stderr in an operator-visible log.
- Take livestream URLs from `puda machine info <machine_id>` (`livestreams`); do not hard-code them.
