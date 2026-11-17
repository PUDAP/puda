# Manual session and CLI dispatch

## Required lifecycle

Every manual-control UI **must** drive these CLI commands:

| Control | CLI |
|---------|-----|
| **Start** | `puda machine start <machine_ids> --run-id manual` |
| Machine actions | `puda machine run <machine_id> <command_name> --params '<json-object>' --run-id manual` |
| **Complete** | `puda machine complete <machine_ids> --run-id manual` |

A **Reset** control (`puda machine reset <machine_ids>`) is optional; add it when the operator needs recovery from the UI.

### UI state machine

1. **Idle (default):** Enable **Start**. Disable machine actions and **Complete**.
2. **Start:** mark the session started only if the command succeeds. Then enable machine actions and **Complete**.
3. **Complete:** use the same machine set and run ID as Start. Return to idle only on success.
4. **Reset (optional):** return to idle after a successful reset.

Do not send machine action commands until **Start** has succeeded for the current session.

## CLI backend

Always invoke `puda` from the project root (where `puda.config` / `project.md` live). Capture stdout/stderr and show failures in the UI.

If `puda machine start` or `puda machine complete` is missing / unknown, tell the user to update the PUDA CLI to version **>= 0.0.36** (e.g. `puda version`, then `puda update`).

`<machine_ids>` may be comma-separated (e.g. `biologic,first`). Start and Complete must hit the **same** set for a session. Resolve targets from project memory, user selection, or workflow skill; discover with `puda machine list` when needed.

### Dispatch individual actions

- `puda machine run` queues exactly one command and does not send START or COMPLETE; invoke it only after manual Start succeeds.
- Always pass `--run-id manual` so actions belong to the open manual session.
- Serialize parameters as a JSON object with `--params`; use `--kwargs '<json-object>'` only when a command requires keyword arguments. Commands with `safety.confirm=true` prompt unless `--yes` is set; obtain operator confirmation in the UI before passing `--yes`.
- Use a subprocess call with an argument list (no shell), `cwd=<PUDA project root>`, captured output, and a per-command timeout.
- Record the invoked CLI command, exit code, stdout, and stderr in the operator-facing command log. Surface failures without changing session state.

### Prohibited dispatch paths

Do not generate temporary protocol JSON/YAML files, invoke `puda protocol run`, or use a custom NATS-publishing helper or parallel NATS client for action controls. Those paths duplicate maintained CLI dispatch, can add unintended lifecycle semantics, and leave stale protocol artifacts.

Prefer a small helper (e.g. `puda_cli.py`) that wraps start / run / complete (and reset, if present) so UI controls stay thin.

## Framework notes

Keep session state and the command log in the framework's state store. In Streamlit, for example, use `st.session_state`; if action controls run inside `@st.fragment`, render the command log inside that same fragment, because a fragment rerun does not refresh a page-level log.
