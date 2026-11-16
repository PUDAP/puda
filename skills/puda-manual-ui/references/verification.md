# Manual dashboard verification

## Scaffold checklist

When creating a new manual-control app:

- [ ] Streamlit entrypoint (e.g. `app.py` / `streamlit_app.py`)
- [ ] Session state: idle vs started; list of relevant `machine_id`s
- [ ] **Start**, **Complete**, **Reset** always present
- [ ] Idle: enable **Start** and **Reset**; disable machine actions and **Complete**
- [ ] Start → `puda machine start … --run-id manual`
- [ ] Complete → `puda machine complete … --run-id manual`
- [ ] Reset → `puda machine reset <machine_id>`
- [ ] Actions → `puda machine run … --run-id manual` (no temp protocols / direct NATS)
- [ ] Machine action buttons only enabled after Start
- [ ] Command log inside the same `@st.fragment` as action buttons (if fragments are used)
- [ ] Single-screen layout with livestream when a camera is available

## Verification

Before reporting a dashboard update as complete:

1. Run the dashboard virtualenv's `python -m py_compile app.py`.
2. Confirm the source contains the direct `machine run` path and no references to temp protocol creation, `puda protocol run`, or custom direct-NATS dispatch.
3. Confirm Streamlit is running.
4. Check `http://127.0.0.1:<port>/_stcore/health` returns HTTP 200.
5. Only provide a Tailnet URL after its health endpoint also succeeds.
