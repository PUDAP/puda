"""Run management for the Opentrons OT-2.

Provides functions to create, start, pause, stop and monitor protocol runs
via the OT-2 HTTP API.

Typical flow::

    from opentrons_driver.core.http_client import OT2HttpClient
    from opentrons_driver.controllers.protocol import upload_protocol
    from opentrons_driver.controllers.run import create_run, play_run, wait_for_completion

    client = OT2HttpClient("192.168.50.64")
    protocol_id = upload_protocol(client, open("my_protocol.py").read())
    run_id = create_run(client, protocol_id)
    play_run(client, run_id)
    result = wait_for_completion(client, run_id)
    print(result["run_status"])   # "succeeded" / "failed" / "stopped"
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from opentrons_driver.core.http_client import OT2HttpClient

logger = logging.getLogger(__name__)

# Terminal run states — polling stops when one of these is observed.
_TERMINAL_STATES = {"succeeded", "failed", "stopped"}


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def create_run(client: OT2HttpClient, protocol_id: str) -> str:
    """Create a run for the given *protocol_id* and return the run ID.

    Args:
        client: Connected :class:`~opentrons_driver.core.http_client.OT2HttpClient`.
        protocol_id: Protocol ID returned by
            :func:`~opentrons_driver.controllers.protocol.upload_protocol`.

    Returns:
        The ``runId`` string assigned by the robot.

    Raises:
        RuntimeError: If the robot returns an error or no run ID.
    """
    resp = client.post("/runs", json={"data": {"protocolId": protocol_id}})
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to create run (HTTP {resp.status_code}): {resp.text}"
        )
    run_id = resp.json().get("data", {}).get("id")
    if not run_id:
        raise RuntimeError(f"Run created but no ID returned. Response: {resp.text}")
    logger.info("Run created: id=%s protocol_id=%s", run_id, protocol_id)
    return run_id


def _send_action(client: OT2HttpClient, run_id: str, action_type: str) -> bool:
    """POST an action to ``/runs/{run_id}/actions``."""
    resp = client.post(
        f"/runs/{run_id}/actions",
        json={"data": {"actionType": action_type}},
    )
    ok = resp.status_code in (200, 201)
    if ok:
        logger.info("Action '%s' sent to run %s", action_type, run_id)
    else:
        logger.error(
            "Action '%s' failed for run %s (HTTP %s): %s",
            action_type,
            run_id,
            resp.status_code,
            resp.text,
        )
    return ok


def play_run(client: OT2HttpClient, run_id: str) -> bool:
    """Start (or resume) a run.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    return _send_action(client, run_id, "play")


def pause_run(client: OT2HttpClient, run_id: str) -> bool:
    """Pause a running protocol.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    return _send_action(client, run_id, "pause")


def stop_run(client: OT2HttpClient, run_id: str) -> bool:
    """Stop (cancel) a run.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    return _send_action(client, run_id, "stop")


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def _extract_current_command(commands_data: list[dict]) -> tuple[Optional[str], Optional[dict], Optional[int]]:
    """Return ``(commandType, command_details, step_index)`` for the most relevant command."""
    # Prefer the most recent "running" command, fall back to queued, then last succeeded.
    for label, predicate in [
        ("running", lambda s: s == "running"),
        ("queued", lambda s: s == "queued"),
        ("succeeded", lambda s: s == "succeeded"),
    ]:
        for i in range(len(commands_data) - 1, -1, -1):
            cmd = commands_data[i]
            if predicate(cmd.get("status", "")):
                return (
                    cmd.get("commandType"),
                    {
                        "commandType": cmd.get("commandType"),
                        "status": cmd.get("status"),
                        "params": cmd.get("params", {}),
                        "id": cmd.get("id"),
                        "key": cmd.get("key"),
                    },
                    i + 1,  # 1-indexed step number
                )
    return None, None, None


def get_run_status(
    client: OT2HttpClient,
    run_id: Optional[str] = None,
) -> dict:
    """Retrieve detailed status for a run.

    Args:
        client: Connected :class:`~opentrons_driver.core.http_client.OT2HttpClient`.
        run_id: Specific run ID.  When ``None`` the most recent run is used.

    Returns:
        A dict with keys:
        ``status``, ``run_id``, ``robot_ip``, ``run_status``,
        ``current_command``, ``command_details``, ``errors``,
        ``started_at``, ``completed_at``, ``run_data``.
    """
    # Normalise "None" strings coming from MCP tool callers
    if run_id is not None and (
        not str(run_id).strip() or str(run_id).strip().lower() == "none"
    ):
        run_id = None

    if run_id:
        return _get_specific_run_status(client, run_id)
    return _get_latest_run_status(client)


def _get_specific_run_status(client: OT2HttpClient, run_id: str) -> dict:
    resp = client.get(f"/runs/{run_id}", timeout=5)
    if resp.status_code != 200:
        return {
            "status": "error",
            "robot_ip": client.robot_ip,
            "error": f"HTTP {resp.status_code}",
            "response": resp.text,
        }

    run_data = resp.json().get("data", {})
    current_command, command_details, step_index = None, None, None

    try:
        cmd_resp = client.get(f"/runs/{run_id}/commands", timeout=5)
        if cmd_resp.status_code == 200:
            current_command, command_details, step_index = _extract_current_command(
                cmd_resp.json().get("data", [])
            )
    except Exception:
        pass

    return {
        "status": "success",
        "run_id": run_id,
        "robot_ip": client.robot_ip,
        "run_status": run_data.get("status", "unknown"),
        "current_step": step_index,
        "current_command": current_command,
        "command_details": command_details,
        "errors": run_data.get("errors", []),
        "started_at": run_data.get("startedAt"),
        "completed_at": run_data.get("completedAt"),
        "run_data": run_data,
    }


def _get_latest_run_status(client: OT2HttpClient) -> dict:
    resp = client.get("/runs", timeout=5)
    if resp.status_code != 200:
        return {
            "status": "error",
            "robot_ip": client.robot_ip,
            "error": f"HTTP {resp.status_code}",
        }

    runs_data = resp.json().get("data", [])
    if not runs_data:
        return {
            "status": "success",
            "robot_ip": client.robot_ip,
            "message": "No runs found on robot",
            "runs": [],
        }

    latest = runs_data[0]
    latest_id = latest.get("id")
    current_command, command_details, step_index = None, None, None

    if latest_id:
        try:
            cmd_resp = client.get(f"/runs/{latest_id}/commands", timeout=5)
            if cmd_resp.status_code == 200:
                current_command, command_details, step_index = _extract_current_command(
                    cmd_resp.json().get("data", [])
                )
        except Exception:
            pass

    return {
        "status": "success",
        "run_id": latest_id,
        "robot_ip": client.robot_ip,
        "run_status": latest.get("status", "unknown"),
        "current_step": step_index,
        "current_command": current_command,
        "command_details": command_details,
        "errors": latest.get("errors", []),
        "started_at": latest.get("startedAt"),
        "completed_at": latest.get("completedAt"),
        "run_data": latest,
    }


# ---------------------------------------------------------------------------
# Blocking wait
# ---------------------------------------------------------------------------


def wait_for_completion(
    client: OT2HttpClient,
    run_id: str,
    max_wait: int = 300,
    poll_interval: int = 3,
) -> dict:
    """Poll until *run_id* reaches a terminal state or *max_wait* seconds elapse.

    Args:
        client: Connected :class:`~opentrons_driver.core.http_client.OT2HttpClient`.
        run_id: Run ID to monitor.
        max_wait: Maximum seconds to wait.  Defaults to ``300``.
        poll_interval: Seconds between status polls.  Defaults to ``3``.

    Returns:
        A dict with at minimum ``run_status`` (e.g. ``"succeeded"``),
        ``run_id``, and ``elapsed_seconds``.
    """
    elapsed = 0
    logger.info("Monitoring run %s (max_wait=%ss)", run_id, max_wait)

    while elapsed < max_wait:
        try:
            status_info = get_run_status(client, run_id)
            run_status = status_info.get("run_status", "unknown")
            logger.debug("Run %s status=%s elapsed=%ss", run_id, run_status, elapsed)

            if run_status in _TERMINAL_STATES:
                status_info["elapsed_seconds"] = elapsed
                return status_info

        except Exception as exc:
            logger.warning("Error polling run status: %s", exc)

        time.sleep(poll_interval)
        elapsed += poll_interval

    logger.warning("Timed out waiting for run %s after %ss", run_id, max_wait)
    return {
        "status": "timeout",
        "run_id": run_id,
        "robot_ip": client.robot_ip,
        "run_status": "timeout",
        "elapsed_seconds": elapsed,
        "message": f"Monitoring timed out after {max_wait}s. Check the robot for current status.",
    }
