---
name: puda-manual-ui
description: Build PUDA manual-control Streamlit dashboards with Start/Complete/Reset sessions, individual CLI command buttons, jogging controls, and livestreams.
---

# PUDA manual UI

Build Streamlit operator UIs backed by subprocess calls to the PUDA CLI. Install Streamlit with uv or pip and use its Streamlit skill for layout, widgets, and styling.

## Workflow and references

1. Read [session lifecycle and CLI dispatch](references/session-and-dispatch.md) before implementing or changing controls. It defines Start/Complete/Reset transitions, CLI arguments, errors, and fragment logging.
2. For dashboard layout, video, or deployed URLs, read [layout and livestream](references/layout-and-livestream.md).
3. When a worked example helps, adapt [the First/Qubot dashboard](references/first-manual-app.py); do not import it as a runtime dependency.
4. Before reporting completion, follow [the scaffold and verification checks](references/verification.md).

## Invariants

- Always include **Start**, **Complete**, and **Reset**. Idle enables Start/Reset; machine actions and Complete require a successful Start.
- Run CLI calls from the PUDA project root, using the same machine set and hard-coded `--run-id manual` for Start, Complete, and actions. Change session state only after successful lifecycle calls; a successful Reset returns to idle.
- Dispatch every action with `puda machine run <machine_id> <command_name> --params '<json-object>' --run-id manual`. Use `subprocess.run` with captured output and a per-command timeout.
- Do not dispatch actions through temporary protocols, `puda protocol run`, a custom publisher, or a parallel NATS client.
- Show command, exit code, stdout, and stderr in the session log. If buttons use `@st.fragment`, render the log inside that same fragment and expand it after a result.
- Verify local and shared URL health endpoints before reporting a deployed dashboard reachable.
