# Manual session and CLI dispatch

## Required session controls

Every manual-control UI **must** include these three buttons:

| Button | Role |
|--------|------|
| **Start** | Open a manual run on all relevant machines |
| **Complete** | Close the manual run on all relevant machines |
| **Reset** | Reset a machine via CLI |

### UI state machine

1. **Idle (default):** Enable **Start** and **Reset**. Disable all machine actions and **Complete**.
2. **Start** must run from the PUDA project root:
   ```bash
   puda machine start <machine_ids> --run-id manual
   ```
   Set `st.session_state.started = True` only if it succeeds. Then enable machine actions and **Complete**.
3. **Complete** must run the same machine set and run ID:
   ```bash
   puda machine complete <machine_ids> --run-id manual
   ```
   Return to idle only on success.
4. **Reset** remains visible in every state and runs:
   ```bash
   puda machine reset <machine_id>
   ```
   Return to idle after a successful reset.

Do not send machine action commands until **Start** has succeeded for the current session.

## CLI backend

Always invoke `puda` from the project root (where `puda.config` / `project.md` live). Capture stdout/stderr and show failures in the UI.

If `puda machine start` or `puda machine complete` is missing / unknown, tell the user to update the PUDA CLI to version **>= 0.0.36** (e.g. `puda version`, then `puda update`).

`<machine_ids>` may be comma-separated (same pattern as `puda machine reset biologic,first`). Start and Complete must hit the **same** set for a session. Resolve targets from project memory, user selection, or workflow skill; discover with `puda machine list` when needed.

### Dispatch individual actions

Use the maintained CLI path for *every* action button:

```bash
puda machine run <machine_id> <command_name> --params '<json-object>' --run-id manual
```

Implement with `subprocess.run(..., cwd=<PUDA project root>, capture_output=True, text=True, timeout=<per-command timeout>)`.

- `puda machine run` queues exactly one command and does not send START or COMPLETE; invoke it only after manual Start succeeds.
- Always pass `--run-id manual` so actions belong to the open manual session.
- Serialize parameters as a JSON object with `--params`; use `--kwargs '<json-object>'` only when a command requires keyword arguments.
- Record the invoked CLI command, exit code, stdout, and stderr in the operator-facing command log.
- Surface failures without changing session state.

### Prohibited legacy dispatch paths

Do not generate temporary protocol JSON/YAML files, invoke `puda protocol run`, or use a custom NATS-publishing helper for dashboard action buttons. Those paths duplicate maintained CLI dispatch, can add unintended lifecycle semantics, and leave stale protocol artifacts.

## Implementation rules

- Backend = subprocess/`puda` only. Do not open a parallel NATS client from the UI.
- Keep `run_id` hard-coded to `"manual"` for Start, Complete, and action dispatch.
- Gate every non-Start/non-Reset control on session state (`started == True`).
- Surface CLI errors; do not flip UI state to “started” or “idle” if the corresponding Start/Complete call failed.
- Prefer a small helper module (e.g. `puda_cli.py`) that wraps start / complete / reset / run / list so buttons stay thin.

## Command log and fragment behavior

Keep the command log in `st.session_state` and show the invoked CLI command, exit code, stdout, and stderr after every action. If action controls run inside `@st.fragment`, render the command log **inside that same fragment**: clicking a fragment button reruns the fragment only, so a page-level log renderer will remain stale. Expand the log automatically after a command result is recorded.
