# Manual UI verification

## Checklist

- [ ] Session state: idle vs started; list of relevant `machine_id`s
- [ ] Start → `puda machine start … --run-id manual`
- [ ] Actions → `puda machine run … --run-id manual` (no temp protocols / direct NATS), enabled only after Start
- [ ] Complete → `puda machine complete … --run-id manual` with the Start machine set
- [ ] Optional Reset → `puda machine reset <machine_ids>`
- [ ] Command log shows command, exit code, stdout, and stderr after every action
- [ ] Livestream URLs come from `puda machine info <machine_id>` `livestreams`

## Verification

Before reporting a manual UI update as complete:

1. Run the project's syntax or build check (e.g. `python -m py_compile app.py` in the UI's environment).
2. Confirm the source contains the direct `machine run` path and no temp protocol creation, `puda protocol run`, or custom direct-NATS dispatch.
3. Confirm the UI process is running and its local health or root endpoint returns HTTP 200.
4. Only provide a shared (e.g. Tailnet) URL after that URL also succeeds.
