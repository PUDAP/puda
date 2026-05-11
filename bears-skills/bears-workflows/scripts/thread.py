"""
Threaded monitors for viscosity optimization workflows.

- ``monitor_balance_threaded``         — stream mass readings from the PUDA
  balance via NATS (``puda machine watch``, subject ``puda.balance.tlm.pos``)
  at ~4 Hz concurrently with an OT-2 run.
- ``monitor_protocol_status_threaded`` — poll OT-2 run status and collect
  protocol commands via HTTP; sets ``stop_event`` when the run is terminal.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)


# ---------------------------------------------------------------------------
# Balance monitor — NATS telemetry via puda machine watch
# ---------------------------------------------------------------------------

def monitor_balance_threaded(
    *,
    sample_name: str = "sample",
    save_csv: bool = True,
    csv_dir: str | None = None,
    stop_event: threading.Event | None = None,
    max_duration: float | None = None,
    result_dict: dict | None = None,
    puda_exe: str | None = None,
) -> None:
    """
    Stream balance readings via NATS (``puda machine watch``) during an OT-2 run.

    Subscribes to ``puda.balance.tlm.pos`` by launching ``puda machine watch``
    as a subprocess and parsing its JSON line output.  Only fresh readings are
    stored (~4 Hz).  The subprocess is terminated when *stop_event* is set or
    *max_duration* seconds have elapsed.

    Args:
        sample_name:  Used to name the output CSV file.
        save_csv:     Write a CSV to *csv_dir* on stop.
        csv_dir:      Output directory.  Defaults to
                      ``reports/viscosity_raw_data``.
        stop_event:   Set by the protocol monitor when the OT-2 run reaches a
                      terminal state.  Balance monitoring stops immediately.
        max_duration: Hard upper bound in seconds.  ``None`` means no limit.
        result_dict:  Updated in-place with ``balance_readings``,
                      ``csv_path``, ``balance_complete``, and optionally
                      ``balance_error``.
        puda_exe:     Path to the ``puda`` executable.  Defaults to
                      ``puda.exe`` in the parent of this script's directory,
                      falling back to ``"puda"`` on PATH.

    Usage::

        from thread import monitor_balance_threaded, monitor_protocol_status_threaded

        stop_event = threading.Event()
        balance_result, protocol_result = {}, {}

        bt = threading.Thread(
            target=monitor_balance_threaded,
            kwargs=dict(sample_name="glycerol_50pct",
                        stop_event=stop_event, max_duration=600,
                        result_dict=balance_result),
            daemon=True,
        )
        pt = threading.Thread(
            target=monitor_protocol_status_threaded,
            kwargs=dict(robot_ip=robot_ip, run_id=run_id,
                        stop_event=stop_event,
                        protocol_start_time=time.time(),
                        result_dict=protocol_result),
            daemon=True,
        )

        bt.start()
        pt.start()
        ot2_client.play(run_id)

        pt.join()
        stop_event.set()   # safety: ensure balance thread stops
        bt.join()

        balance_readings = balance_result["balance_readings"]
        csv_path = balance_result.get("csv_path")
    """
    if csv_dir is None:
        csv_dir = os.path.join("reports", "viscosity_raw_data")
    if result_dict is None:
        result_dict = {}
    if stop_event is None:
        stop_event = threading.Event()

    # Resolve puda executable and working directory
    if puda_exe is None:
        _candidate = Path(__file__).resolve().parent.parent / "puda.exe"
        puda_exe = str(_candidate) if _candidate.exists() else "puda"
    _puda_path = Path(puda_exe)
    cwd = str(_puda_path.parent) if _puda_path.exists() else None

    # Option B fix (S2): launch puda machine watch with a short timeout and
    # restart in a loop, checking stop_event between invocations.  This
    # prevents the blocking `for line in proc.stdout` from hanging forever
    # when the NATS stream goes quiet — the subprocess exits after watch_chunk
    # seconds and we re-check stop_event before relaunching.
    watch_chunk = min(int(max_duration or 30), 30)  # re-launch every ≤30 s

    cmd = [
        puda_exe,
        "machine", "watch",
        "--targets", "balance",
        "--subjects", "pos",
        "--timeout", str(watch_chunk),
    ]

    balance_readings: list[dict] = []
    csv_path: str | None = None
    reading_count = 0
    start_time = time.time()

    print(f"Starting balance monitoring via puda.balance.tlm.pos "
          f"(max {max_duration if max_duration else 'unlimited'} s) ...")

    try:
        while not stop_event.is_set():
            if max_duration is not None and (time.time() - start_time) >= max_duration:
                break

            # Update timeout for the remaining allowed duration
            if max_duration is not None:
                remaining = max_duration - (time.time() - start_time)
                chunk = min(watch_chunk, int(remaining) + 1)
            else:
                chunk = watch_chunk

            chunk_cmd = cmd[:-1] + [str(chunk)]

            proc = subprocess.Popen(
                chunk_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=cwd,
            )

            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    if stop_event.is_set():
                        break
                    if max_duration is not None and (time.time() - start_time) >= max_duration:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line).get("data", {})
                        if not data.get("fresh"):
                            continue
                        mass_g = data.get("mass_g")
                        if mass_g is None:
                            continue
                        mass_mg = data.get("mass_mg") or mass_g * 1000
                        elapsed = time.time() - start_time

                        balance_readings.append({
                            "time": round(elapsed, 3),
                            "mass_mg": mass_mg,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        })
                        reading_count += 1

                        if reading_count % 40 == 0:  # log every ~10 s at 4 Hz
                            print(f"  Balance reading {reading_count}: "
                                  f"{mass_mg:.2f} mg @ {elapsed:.2f} s")

                    except (json.JSONDecodeError, KeyError):
                        pass

            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            # subprocess chunk ended — loop back to check stop_event

        stop_reason = (
            "stop_event" if stop_event.is_set()
            else f"max_duration ({max_duration} s)" if max_duration
            else "subprocess ended"
        )
        print(f"Balance monitoring stopped ({stop_reason}) — "
              f"{reading_count} readings collected.")

        if save_csv and balance_readings:
            try:
                os.makedirs(csv_dir, exist_ok=True)
                safe_name = _sanitize_filename(sample_name)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_path = os.path.join(csv_dir, f"balance_{safe_name}_{ts}.csv")
                if pd is None:
                    print("Cannot save CSV: pandas is not installed.")
                else:
                    pd.DataFrame(balance_readings).to_csv(csv_path, index=False)
                    print(f"Balance data saved: {csv_path} ({len(balance_readings)} readings)")
            except Exception as exc:
                print(f"Could not save balance CSV: {exc}")

        result_dict["balance_readings"] = balance_readings
        result_dict["csv_path"] = csv_path
        result_dict["balance_complete"] = True

    except KeyboardInterrupt:
        print("Balance monitoring interrupted by user.")
        result_dict["balance_readings"] = balance_readings
        result_dict["csv_path"] = csv_path if balance_readings else None
        result_dict["balance_complete"] = True

    except Exception as exc:
        print(f"Balance monitoring error: {exc}")
        result_dict["balance_readings"] = []
        result_dict["csv_path"] = None
        result_dict["balance_complete"] = True
        result_dict["balance_error"] = str(exc)


# ---------------------------------------------------------------------------
# Opentrons protocol monitor — helpers
# ---------------------------------------------------------------------------

def _normalize_cmd_type(ctype: str) -> str:
    """Map raw Opentrons command type strings to a canonical name."""
    cl = ctype.lower()
    if "aspirate" in cl:
        return "aspirate"
    if "dispense" in cl:
        return "dispense"
    if "pick" in cl and "tip" in cl:
        return "pickUpTip"
    if "drop" in cl and "tip" in cl:
        return "dropTip"
    if "delay" in cl or "pausing" in cl or "wait" in cl:
        return "delay"
    if "touch" in cl and "tip" in cl:
        return "touchTip"
    if "blow" in cl:
        return "blowout"
    return ctype


def _parse_cmd(cmd: dict, start_time: float) -> dict | None:
    """
    Parse a single Opentrons command dict.

    Returns a normalised record dict if the command is tracked, else None.
    Prints a human-readable summary as a side-effect.
    """
    ctype = cmd.get("commandType", "")
    params = cmd.get("params", {})
    volume = params.get("volume")
    seconds = params.get("seconds")
    minutes = params.get("minutes")

    well = params.get("wellName") or params.get("well") or params.get("wellLocation")
    labware = params.get("labwareId") or params.get("labware") or params.get("labwareLocation")
    if isinstance(well, dict):
        well = well.get("wellName") or well.get("well") or well.get("name")
    if isinstance(labware, dict):
        labware = labware.get("labwareId") or labware.get("labware") or labware.get("name")
    location = " / ".join(str(x) for x in (labware, well) if x) or "Unknown"

    is_delay_by_params = (
        (seconds is not None or minutes is not None) and volume is None and location == "Unknown"
    )

    cl = ctype.lower()
    tracked = (
        "aspirate" in cl or "dispense" in cl
        or ("pick" in cl and "tip" in cl)
        or ("drop" in cl and "tip" in cl)
        or "delay" in cl or "pausing" in cl or "wait" in cl
        or ctype in (
            "aspirate", "dispense", "delay", "touchTip", "blowout",
            "pickUpTip", "dropTip", "pickupTip", "pick_up_tip", "drop_tip",
            "Aspirating", "Dispensing", "Pausing", "Touching tip",
            "Blowing out", "picking up tip", "dropping tip", "wait",
        )
        or is_delay_by_params
    )
    if not tracked:
        return None

    ntype = _normalize_cmd_type(ctype)
    if is_delay_by_params:
        ntype = "delay"

    delay_duration: float | str = ""
    if ntype == "delay":
        delay_duration = seconds if seconds is not None else (minutes * 60 if minutes is not None else "")

    if ntype in ("aspirate", "dispense"):
        vol_str = f" {volume} µL" if volume is not None else ""
        print(f"   [CMD] {ntype.capitalize()}{vol_str} | Location: {location}")
    elif ntype == "delay":
        print(f"   [DELAY] Pausing{f' {delay_duration}s' if delay_duration else ''}")
    else:
        print(f"   [CMD] {ntype}")

    return {
        "elapsed_time": time.time() - start_time,
        "command_type": ntype,
        "volume": volume if volume is not None else "",
        "location": location,
        "seconds": delay_duration if ntype == "delay" else (seconds if seconds is not None else ""),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }


# ---------------------------------------------------------------------------
# Opentrons protocol monitor
# ---------------------------------------------------------------------------

def monitor_protocol_status_threaded(
    robot_ip: str,
    run_id: str | None = None,
    max_wait_time: int = 600,
    check_interval: int = 2,
    api_base_url: str | None = None,  # unused; kept for API compatibility
    result_dict: dict | None = None,
    stop_event: threading.Event | None = None,
    protocol_start_time: float | None = None,
    startup_delay: float = 2.0,
) -> None:
    """
    Monitor an Opentrons protocol run in a background thread.

    Polls the robot HTTP API for run status and command list, collecting
    aspirate/dispense/delay/tip commands with timestamps.  Sets *stop_event*
    when the protocol reaches a terminal state so the concurrent
    ``monitor_balance_threaded`` thread knows to stop.

    Args:
        robot_ip:             IP address of the OT-2 robot.
        run_id:               Robot HTTP API run ID to monitor.  If *None*
                              the most recent (or currently-running) run is
                              used.

                              **Important:** do NOT pass the puda internal
                              run ID printed as ``"Run ID: ..."`` by
                              ``puda protocol run`` — that is a database
                              tracking ID and is different from the robot's
                              HTTP run ID.  Passing the wrong ID causes every
                              ``GET /runs/{run_id}`` to return HTTP 404 and
                              the function will silently time out after
                              *max_wait_time* seconds.  If an unrecognised ID
                              is supplied the function automatically falls
                              back to the most recently created robot run.
        max_wait_time:        Seconds before timing out.
        check_interval:       Polling interval in seconds.
        api_base_url:         Ignored; present for backward compatibility.
        result_dict:          Updated in-place with ``protocol_status``,
                              ``protocol_complete``, and ``protocol_commands``.
        stop_event:           Set when the protocol finishes so paired threads
                              can exit cleanly.
        protocol_start_time:  ``time.time()`` reference for elapsed timestamps.
        startup_delay:        Seconds to wait after startup before polling
                              begins.  Allows the robot time to register the
                              run.  Default is ``2.0`` s; increase if the
                              robot is slow to initialise.
    """
    if result_dict is None:
        result_dict = {}
    if stop_event is None:
        stop_event = threading.Event()
    if protocol_start_time is None:
        protocol_start_time = time.time()

    base_url = f"http://{robot_ip}:31950"
    hdrs = {"opentrons-version": "*"}

    print(">> Starting protocol status and command monitoring...")
    print(f"   Robot IP: {robot_ip}")
    print(f"   Run ID: {run_id or 'None (will use latest run)'}")
    print("   [STATUS] Protocol execution status updates will be shown below:\n")
    print(f"   [WAIT] Waiting {startup_delay}s for protocol to initialize...")
    time.sleep(startup_delay)

    # S3 fix: puda protocol run prints its own internal database ID as
    # "Run ID: ..." which is NOT the robot HTTP run ID.  If the caller
    # passes that ID, every GET /runs/{run_id} returns 404 and the function
    # silently burns the full max_wait_time.  Detect this early by probing
    # the run once; on 404 fall back to the most recently created robot run.
    if run_id is not None:
        try:
            _probe = requests.get(f"{base_url}/runs/{run_id}", headers=hdrs, timeout=5)
            if _probe.status_code == 404:
                print(f"   [WARN] Run ID {run_id!r} not found on robot "
                      f"(may be a puda internal ID). Resolving from robot run list...")
                _runs_resp = requests.get(f"{base_url}/runs", headers=hdrs, timeout=5)
                _runs = _runs_resp.json().get("data", []) if _runs_resp.ok else []
                if _runs:
                    run_id = _runs[-1]["id"]
                    print(f"   [OK] Resolved robot run ID: {run_id}")
                else:
                    print("   [WARN] No runs found on robot; will poll for a new run.")
                    run_id = None
        except Exception as _exc:
            print(f"   [WARN] Could not probe run ID: {_exc}")

    seen_ids: set[str] = set()
    commands: list[dict] = []
    last_status: str | None = None
    initial_run_id = run_id
    run_id_verified = False
    last_warning = 0.0
    conn_errors = 0
    elapsed = 0
    protocol_complete = False

    def _finish(status: str) -> None:
        nonlocal protocol_complete
        print(f"[OK] Protocol completed with status: {status}")
        result_dict.update(protocol_status=status, protocol_complete=True,
                           protocol_commands=commands)
        stop_event.set()
        protocol_complete = True

    def _collect_commands(rid: str) -> None:
        resp = requests.get(f"{base_url}/runs/{rid}/commands", headers=hdrs, timeout=3)
        if not resp.ok:
            return
        for cmd in resp.json().get("data", []):
            cid = cmd["id"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            record = _parse_cmd(cmd, protocol_start_time)
            if record:
                commands.append(record)

    try:
        while elapsed < max_wait_time and not protocol_complete:
            status: str | None = None
            current_run_id = run_id

            try:
                # --- Try the specific run first ---
                if run_id:
                    resp = requests.get(f"{base_url}/runs/{run_id}", headers=hdrs, timeout=3)
                    if resp.ok:
                        data = resp.json().get("data", {})
                        status = data.get("status", "unknown")
                        current_run_id = data.get("id", run_id)
                        if not run_id_verified:
                            run_id_verified = True
                            print(f"   [OK] Verified monitoring run ID: {current_run_id}")
                        if status != last_status:
                            print(f"   [STATUS] Protocol status: {status}")
                            last_status = status
                        _collect_commands(run_id)
                        conn_errors = 0
                    elif resp.status_code == 404:
                        conn_errors += 1  # triggers fallback below
                    else:
                        conn_errors += 1
                        if conn_errors == 1:
                            print(f"   [WARN] Error getting run status: {resp.status_code}")

                # --- Fallback: scan all runs ---
                if not run_id or conn_errors > 0:
                    runs_resp = requests.get(f"{base_url}/runs", headers=hdrs, timeout=3)
                    if runs_resp.ok:
                        all_runs = runs_resp.json().get("data", [])
                        if not all_runs:
                            conn_errors += 1
                            if conn_errors == 1:
                                print("   [WARN] No runs found on robot")
                        else:
                            # Prefer our initial run; then most-recent running; then latest
                            target = (
                                next((r for r in all_runs if r.get("id") == initial_run_id), None)
                                or max(
                                    (r for r in all_runs if r.get("status") == "running"),
                                    key=lambda r: r.get("createdAt", ""),
                                    default=None,
                                )
                                or all_runs[0]
                            )
                            run_id = target.get("id")
                            status = target.get("status", "unknown")
                            current_run_id = run_id
                            if not run_id_verified:
                                if not initial_run_id:
                                    initial_run_id = run_id
                                run_id_verified = True
                                print(f"   [OK] Using run ID: {run_id}")
                            conn_errors = 0
                            _collect_commands(run_id)
                            if status != last_status:
                                print(f"   [STATUS] Protocol status: {status}")
                                last_status = status
                    else:
                        conn_errors += 1
                        if conn_errors == 1:
                            print(f"   [WARN] Error getting runs list: {runs_resp.status_code}")

                # --- Check for terminal status ---
                if status in ("succeeded", "failed", "stopped"):
                    if run_id_verified:
                        _finish(status)
                        break
                    else:
                        now = time.time()
                        if now - last_warning >= 30:
                            print(f"   [WARN] Run {current_run_id} is {status}; waiting to verify our run")
                            last_warning = now
                elif status == "running" and elapsed > 0 and elapsed % 10 == 0:
                    print(f"   [ROBOT] Protocol still running... ({elapsed}s elapsed, {len(commands)} commands)")

            except requests.exceptions.Timeout:
                conn_errors += 1
                if conn_errors == 1:
                    print(f"   [WARN] Timeout connecting to robot at {robot_ip}:31950")
            except requests.exceptions.ConnectionError as exc:
                conn_errors += 1
                if conn_errors == 1:
                    print(f"   [WARN] Cannot connect to robot at {robot_ip}:31950\n      {exc}")
            except Exception as exc:
                conn_errors += 1
                if conn_errors <= 3:
                    print(f"   [WARN] Protocol monitoring error: {exc}")

            time.sleep(check_interval)
            elapsed += check_interval

        if not protocol_complete:
            print("[WARN] Timeout waiting for protocol completion")
            result_dict.update(protocol_status="timeout", protocol_complete=True,
                               protocol_commands=commands)
            stop_event.set()

    except Exception as exc:
        print(f"[ERROR] Protocol monitoring error: {exc}")
        result_dict.update(protocol_status="error", protocol_complete=True,
                           protocol_commands=commands, protocol_error=str(exc))
        stop_event.set()
