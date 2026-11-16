import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_DIR = Path("/home/puda/workspace/puda")
MACHINE_ID = "first"
BIOLOGIC_MACHINE_ID = "biologic"
MACHINE_IDS = (MACHINE_ID, BIOLOGIC_MACHINE_ID)
MACHINE_IDS_ARG = ",".join(MACHINE_IDS)
MANUAL_RUN_ID = "manual"
LIVESTREAM_URL = "http://first.taimen-truck.ts.net:8888/livestream/"
LIVESTREAM_API_URL = "http://first.taimen-truck.ts.net:8889/livestream/"

st.set_page_config(
    page_title="First manual jogging",
    page_icon=":material/precision_manufacturing:",
    layout="wide",
)

# The lifecycle controls use semantic colors: Complete is green and Reset is red.
# Streamlit assigns a stable `st-key-<key>` class to keyed widgets.
st.html(
    """
    <style>
      .st-key-complete-manual button:not(:disabled) {
        background-color: #198754;
        border-color: #198754;
        color: #ffffff;
      }
      .st-key-complete-manual button:not(:disabled):hover {
        background-color: #146c43;
        border-color: #146c43;
      }
      .st-key-reset-machine button:not(:disabled) {
        background-color: #c62828;
        border-color: #c62828;
        color: #ffffff;
      }
      .st-key-reset-machine button:not(:disabled):hover {
        background-color: #9f1f1f;
        border-color: #9f1f1f;
      }
    </style>
    """
)

# The available Biologic methods use the schemas reported by
# `puda machine commands biologic`. Channel 0 is the First/Biologic default.
BIOLOGIC_METHOD_DEFAULTS: dict[str, dict[str, Any]] = {
    "startup": {},
    "OCV": {"time": 60.0, "time_interval": 1.0, "voltage_interval": 0.01, "channels": [0], "retrieve_data": True},
    "CV": {"start": 0.0, "end": 0.5, "E2": 0.0, "Ef": 0.0, "step": 0.01, "rate": 0.01, "N_Cycles": 1, "channels": [0], "retrieve_data": True},
    "CA": {"voltages": [0.0], "durations": [60.0], "channels": [0], "retrieve_data": True},
    "CP": {"currents": [0.001], "durations": [60.0], "channels": [0], "retrieve_data": True},
    "PEIS": {"voltage": 0.0, "amplitude_voltage": 0.01, "initial_frequency": 100000.0, "final_frequency": 1.0, "frequency_number": 20, "duration": 1.0, "channels": [0], "retrieve_data": True},
    "GEIS": {"current": 0.001, "amplitude_current": 0.0001, "initial_frequency": 100000.0, "final_frequency": 1.0, "frequency_number": 20, "duration": 1.0, "channels": [0], "retrieve_data": True},
    "MPP": {"run_time": 60.0, "channels": [0], "data": "data", "by_channel": False, "cv": {}},
    "MPP_Cycles": {"run_time": 60.0, "cycles": 1, "channels": [0], "data": "data", "by_channel": False, "cv": {}},
    "MPP_Tracking": {"run_time": 60.0, "init_vmpp": 0.0, "channels": [0], "folder": None, "by_channel": False},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_state() -> None:
    st.session_state.setdefault("started", False)
    st.session_state.setdefault("state_synced", False)
    st.session_state.setdefault("command_log", [])
    st.session_state.setdefault("last_state", None)
    st.session_state.setdefault("last_result", None)


def remember(result: dict[str, Any]) -> dict[str, Any]:
    st.session_state.command_log.insert(0, result)
    st.session_state.command_log = st.session_state.command_log[:40]
    return result


def parameter_error(command: str, message: str) -> dict[str, Any]:
    """Store UI-side validation failures in the same visible command log."""
    return remember(
        {
            "started": now_iso(),
            "finished": now_iso(),
            "cmd": command,
            "exit_code": 2,
            "output": message,
        }
    )


def run_cli(args: list[str], timeout: int = 180) -> dict[str, Any]:
    puda_bin = shutil.which("puda") or "puda"
    cmd = [puda_bin] + args
    started_at = now_iso()
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_DIR,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return remember(
            {
                "started": started_at,
                "finished": now_iso(),
                "cmd": " ".join(shlex.quote(part) for part in cmd),
                "exit_code": proc.returncode,
                "output": output,
            }
        )
    except subprocess.TimeoutExpired as exc:
        return remember(
            {
                "started": started_at,
                "finished": now_iso(),
                "cmd": " ".join(shlex.quote(part) for part in cmd),
                "exit_code": 124,
                "output": f"Timed out after {timeout}s.\nSTDOUT:\n{exc.stdout or ''}\nSTDERR:\n{exc.stderr or ''}".strip(),
            }
        )


def query_machine_state() -> dict[str, Any] | None:
    puda_bin = shutil.which("puda") or "puda"
    try:
        proc = subprocess.run(
            [puda_bin, "machine", "state", *MACHINE_IDS],
            cwd=PROJECT_DIR,
            text=True,
            capture_output=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return None
        return json.loads(((proc.stdout or "") + (proc.stderr or "")).strip())
    except Exception:
        return None


def sync_started_from_machine_state() -> None:
    """Synchronize a new browser session without clobbering local UI state.

    The First edge's state endpoint can briefly report ``idle`` after accepting
    a manual start. Re-reading it on every Streamlit rerun reset ``started``
    before the controls were rendered, which left every machine-action button
    disabled immediately after Start.
    """
    state = query_machine_state()
    st.session_state.state_synced = True
    if not state:
        return
    st.session_state.last_state = state
    machines = state.get("machines", {})
    st.session_state.started = all(
        machines.get(machine_id, {}).get("ok")
        and machines[machine_id].get("state", {}).get("state") == "active"
        and machines[machine_id].get("state", {}).get("run_id") == MANUAL_RUN_ID
        for machine_id in MACHINE_IDS
    )


def require_started(action: str) -> bool:
    if st.session_state.started:
        return True
    remember(
        {
            "started": now_iso(),
            "finished": now_iso(),
            "cmd": action,
            "exit_code": 2,
            "output": "Manual run is not started. Press Start first; all machine actions are disabled while idle.",
        }
    )
    return False


def start_manual() -> dict[str, Any]:
    result = run_cli(["machine", "start", MACHINE_IDS_ARG, "--run-id", MANUAL_RUN_ID], timeout=60)
    if result["exit_code"] == 0:
        st.session_state.started = True
    elif "manual is currently running" in result.get("output", ""):
        # A prior browser may have opened the session. Treat it as recovered only
        # when *both* configured machines are in the required manual run.
        sync_started_from_machine_state()
        if st.session_state.started:
            result = dict(result)
            result["exit_code"] = 0
            result["output"] = result.get("output", "") + "\n\nUI synchronized: manual run was already active on both machines."
            st.session_state.command_log[0] = result
    return result


def complete_manual() -> dict[str, Any]:
    result = run_cli(["machine", "complete", MACHINE_IDS_ARG, "--run-id", MANUAL_RUN_ID], timeout=60)
    if result["exit_code"] == 0:
        st.session_state.started = False
    else:
        sync_started_from_machine_state()
    return result


def reset_machine() -> dict[str, Any]:
    result = run_cli(["machine", "reset", MACHINE_IDS_ARG], timeout=120)
    if result["exit_code"] == 0:
        st.session_state.started = False
    else:
        sync_started_from_machine_state()
    return result


def run_control_callback(action) -> None:
    """Run a lifecycle action before Streamlit renders the next page state."""
    st.session_state.last_result = action()


def run_machine_command(
    name: str,
    params: dict[str, Any] | None = None,
    timeout: int = 240,
    machine_id: str = MACHINE_ID,
) -> dict[str, Any]:
    """Run one queued command via `puda machine run` in the manual session."""
    if not require_started(name):
        return st.session_state.command_log[0]
    return run_cli(
        [
            "machine",
            "run",
            machine_id,
            name,
            "--params",
            json.dumps(params or {}, separators=(",", ":")),
            "--run-id",
            MANUAL_RUN_ID,
        ],
        timeout=timeout,
    )


def home_machine() -> dict[str, Any]:
    return run_machine_command("home", {}, timeout=240)


def state_snapshot() -> dict[str, Any]:
    result = run_cli(["machine", "state", *MACHINE_IDS], timeout=30)
    if result["exit_code"] == 0:
        try:
            st.session_state.last_state = json.loads(result["output"])
        except json.JSONDecodeError:
            st.session_state.last_state = result["output"]
    return result


def render_result(result: dict[str, Any]) -> None:
    st.session_state.last_result = result
    if result.get("exit_code") == 0:
        st.toast("Command completed", icon=":material/check_circle:")
    else:
        st.toast(f"Command failed with exit code {result.get('exit_code')}", icon=":material/error:")


init_state()
if not st.session_state.state_synced:
    sync_started_from_machine_state()
controls_disabled = not st.session_state.started

st.title("First machine manual jogging")

# Keep the live camera outside this fragment. A command-button interaction
# reruns only this control surface, so the iframe is not marked stale or remounted.
controls_col, camera_col = st.columns([1.05, 1.55], gap="medium")


@st.fragment
def render_control_surface() -> None:
    # This is evaluated on every fragment-scoped rerun after a command callback.
    controls_disabled = not st.session_state.started
    with controls_col:
        with st.container(border=True):
            st.caption(
                f"Targets: `{MACHINE_IDS_ARG}` · Run: {'Started' if st.session_state.started else 'Idle'}"
            )
            with st.container(horizontal=True):
                st.button(
                    "Start",
                    type="primary",
                    icon=":material/play_arrow:",
                    disabled=st.session_state.started,
                    on_click=run_control_callback,
                    args=(start_manual,),
                )
                st.button(
                    "Complete",
                    key="complete-manual",
                    icon=":material/check_circle:",
                    disabled=not st.session_state.started,
                    on_click=run_control_callback,
                    args=(complete_manual,),
                )
                st.button(
                    "Reset",
                    key="reset-machine",
                    icon=":material/restart_alt:",
                    disabled=False,
                    on_click=run_control_callback,
                    args=(reset_machine,),
                )
                if st.button("Refresh", icon=":material/refresh:"):
                    render_result(state_snapshot())

        if st.session_state.last_result:
            r = st.session_state.last_result
            if r.get("exit_code") == 0:
                st.success(f"Last command completed: `{r.get('cmd', '')}`")
            else:
                st.error(f"Last command failed ({r.get('exit_code')}): `{r.get('cmd', '')}`")

        with st.container(border=True):
            st.subheader("Motion")
            with st.container(horizontal=True):
                if st.button("Home gantry", icon=":material/home:", disabled=controls_disabled):
                    render_result(home_machine())
                if st.button("Get position", icon=":material/my_location:", disabled=controls_disabled):
                    render_result(run_machine_command("get_position", {}, timeout=120))

            with st.form("move_electrode_form"):
                c1, c2, c3 = st.columns([1, 1, 1])
                deck_slot = c1.selectbox("Deck slot", ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"], index=1, disabled=controls_disabled)
                well_name = c2.text_input("Well", value="A1", disabled=controls_disabled)
                height = c3.number_input("Height (mm)", min_value=0.0, max_value=100.0, value=0.0, step=0.5, disabled=controls_disabled)
                submitted = st.form_submit_button("Move electrode", icon=":material/open_with:", disabled=controls_disabled)
            if submitted:
                render_result(run_machine_command("move_electrode", {"deck_slot": deck_slot, "well_name": well_name.strip(), "height_from_bottom": float(height)}))

        with st.container(border=True):
            st.subheader("Biologic electrochemistry")
            st.caption(
                "All listed Biologic methods dispatch through `puda machine run biologic … --run-id manual`. "
                "Edit the JSON parameters before sending; channel 0 is the default."
            )
            biologic_method = st.selectbox(
                "Method",
                list(BIOLOGIC_METHOD_DEFAULTS),
                key="biologic_method",
                disabled=controls_disabled,
            )
            with st.form("biologic_method_form"):
                biologic_params_text = st.text_area(
                    "Parameters (JSON)",
                    value=json.dumps(BIOLOGIC_METHOD_DEFAULTS[biologic_method], indent=2),
                    key=f"biologic_params_{biologic_method}",
                    height=220,
                    disabled=controls_disabled,
                )
                biologic_submitted = st.form_submit_button(
                    f"Run Biologic {biologic_method}",
                    icon=":material/science:",
                    disabled=controls_disabled,
                )
            if biologic_submitted:
                try:
                    biologic_params = json.loads(biologic_params_text)
                    if not isinstance(biologic_params, dict):
                        raise ValueError("Parameters must be a JSON object.")
                except (json.JSONDecodeError, ValueError) as exc:
                    render_result(
                        parameter_error(
                            f"puda machine run {BIOLOGIC_MACHINE_ID} {biologic_method}",
                            f"Invalid JSON parameters: {exc}",
                        )
                    )
                else:
                    render_result(
                        run_machine_command(
                            biologic_method,
                            biologic_params,
                            timeout=900,
                            machine_id=BIOLOGIC_MACHINE_ID,
                        )
                    )

        with st.container(border=True):
            st.subheader("Liquid handling")
            st.markdown("**Tip**")
            tip_c1, tip_c2, tip_c3 = st.columns([1, 1, 1])
            tip_slot = tip_c1.selectbox("Tip/trash slot", ["C3", "C1", "A1", "A2", "B1", "B2", "C2"], index=0, key="tip_slot", disabled=controls_disabled)
            tip_well = tip_c2.text_input("Tip/trash well", value="A1", key="tip_well", disabled=controls_disabled)
            drop_height = tip_c3.number_input("Drop height", min_value=0.0, max_value=100.0, value=0.0, step=0.5, disabled=controls_disabled)
            with st.container(horizontal=True):
                if st.button("Attach tip", icon=":material/add_circle:", disabled=controls_disabled):
                    render_result(run_machine_command("attach_tip", {"deck_slot": tip_slot, "well_name": tip_well.strip()}))
                if st.button("Drop tip", icon=":material/delete:", disabled=controls_disabled):
                    render_result(run_machine_command("drop_tip", {"deck_slot": tip_slot, "well_name": tip_well.strip(), "height_from_bottom": float(drop_height)}))

            st.markdown("**Aspirate / dispense**")
            l1, l2, l3, l4 = st.columns([1, 1, 1, 1])
            liq_slot = l1.selectbox("Liquid slot", ["C2", "A2", "A1", "B1", "B2", "C1", "C3"], index=0, disabled=controls_disabled)
            liq_well = l2.text_input("Liquid well", value="A1", disabled=controls_disabled)
            amount = l3.number_input("Volume µL", min_value=1, max_value=300, value=10, step=1, disabled=controls_disabled)
            liq_height = l4.number_input("Height", min_value=0.0, max_value=100.0, value=0.0, step=0.5, disabled=controls_disabled)
            params = {"deck_slot": liq_slot, "well_name": liq_well.strip(), "amount": int(amount), "height_from_bottom": float(liq_height)}
            with st.container(horizontal=True):
                if st.button("Aspirate", icon=":material/arrow_upward:", disabled=controls_disabled):
                    render_result(run_machine_command("aspirate_from", params))
                if st.button("Dispense", icon=":material/arrow_downward:", disabled=controls_disabled):
                    render_result(run_machine_command("dispense_to", params))
                if st.button("Blowout", icon=":material/air:", disabled=controls_disabled):
                    render_result(run_machine_command("blowout", {}))

        with st.container(border=True):
            st.subheader("Deck and system")
            d1, d2 = st.columns(2)
            slot = d1.selectbox("Deck slot", ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"], key="labware_slot", disabled=controls_disabled)
            labware = d2.selectbox("Labware", ["trash_bin", "polyelectric_8_wellplate_30000ul", "opentrons_96_tiprack_300ul", "MEA_cell_MTP"], disabled=controls_disabled)
            with st.container(horizontal=True):
                if st.button("Load", icon=":material/inventory_2:", disabled=controls_disabled):
                    render_result(run_machine_command("load_labware", {"deck_slot": slot, "labware_name": labware}))
                if st.button("Remove", icon=":material/remove_circle:", disabled=controls_disabled):
                    render_result(run_machine_command("remove_labware", {"deck_slot": slot}))
                if st.button("Get deck", icon=":material/table_rows:", disabled=controls_disabled):
                    render_result(run_machine_command("get_deck", {}, timeout=120))
            with st.container(horizontal=True):
                if st.button("Startup", icon=":material/play_circle:", disabled=controls_disabled):
                    render_result(run_machine_command("startup", {}))
                if st.button("Pause", icon=":material/pause:", disabled=controls_disabled):
                    render_result(run_machine_command("pause", {}, timeout=60))
                if st.button("Resume", icon=":material/resume:", disabled=controls_disabled):
                    render_result(run_machine_command("resume", {}, timeout=60))
                if st.button("Cancel", icon=":material/cancel:", disabled=controls_disabled):
                    render_result(run_machine_command("cancel", {}, timeout=60))

        # This must stay inside the fragment: machine-action clicks rerun only
        # this control surface, not the camera or page-level content below it.
        with st.expander("Command logs", expanded=bool(st.session_state.last_result)):
            if not st.session_state.command_log:
                st.info("No commands sent from this browser session yet.")
            for item in st.session_state.command_log[:20]:
                st.markdown(f"**{item['finished']} · exit {item['exit_code']}**")
                st.code(item.get("cmd", ""), language="bash")
                if item.get("output"):
                    st.text(item["output"][:2500])

        if st.session_state.last_state is not None:
            with st.expander("Last state snapshot", expanded=False):
                st.json(st.session_state.last_state)


render_control_surface()

with camera_col:
    with st.container(border=True):
        st.subheader("First livestream camera")
        st.caption(f"Player: `{LIVESTREAM_URL}`")
        st.iframe(LIVESTREAM_URL, height=720, width="stretch")
        with st.container(horizontal=True):
            st.link_button("Open camera", LIVESTREAM_URL, icon=":material/open_in_new:")
            st.link_button("8889 endpoint", LIVESTREAM_API_URL, icon=":material/settings_input_antenna:")

st.caption("Built with the PUDA UI skill. Commands run directly through `puda machine run`.")
