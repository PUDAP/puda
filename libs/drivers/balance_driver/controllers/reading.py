"""Balance reading controllers for the Balance Bridge API.

Each function maps 1-to-1 to a Balance Bridge endpoint and raises
:class:`RuntimeError` on failure so callers never have to inspect raw HTTP
status codes.

Typical usage::

    from balance_driver.core.http_client import BalanceBridgeClient
    from balance_driver.controllers import reading as read_ctrl

    client = BalanceBridgeClient()
    read_ctrl.connect_balance(client, port="COM8", baudrate=115200)
    data = read_ctrl.get_latest_reading(client, port="COM8")
    print(data["mass_g"])
"""

from __future__ import annotations

import logging

from balance_driver.core.http_client import BalanceBridgeClient

logger = logging.getLogger(__name__)


def connect_balance(
    client: BalanceBridgeClient,
    port: str,
    baudrate: int = 115200,
    mode: str = "arduino",
    timeout: float = 2.0,
) -> dict:
    """Connect to a balance via the bridge.

    For ``mode="arduino"`` the bridge starts a background serial reader thread
    that continuously caches incoming ADC values.  For ``mode="commercial"``
    the bridge uses a command-response protocol.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port of the balance, e.g. ``"COM8"``.
        baudrate: Serial baud rate.  Defaults to ``115200``.
        mode: ``"arduino"`` or ``"commercial"``.  Defaults to ``"arduino"``.
        timeout: Serial port timeout in seconds.  Defaults to ``2.0``.

    Returns:
        Connection result dict — contains ``status``, ``port``, ``baudrate``,
        ``mode``, and ``message``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    payload = {
        "port": port,
        "baudrate": baudrate,
        "timeout": timeout,
        "mode": mode,
    }
    resp = client.post("/balance/connect", json=payload)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to connect to {port}: HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.info(
        "Balance connected: port=%s baudrate=%s mode=%s status=%s",
        port,
        baudrate,
        mode,
        result.get("status"),
    )
    return result


def disconnect_balance(client: BalanceBridgeClient, port: str) -> dict:
    """Disconnect from a balance and stop its background reader.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port to disconnect.

    Returns:
        Disconnection result dict — contains ``status``, ``port``, ``message``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.post("/balance/disconnect", params={"port": port})
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to disconnect from {port}: HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.info("Balance disconnected: port=%s", port)
    return result


def read_balance(
    client: BalanceBridgeClient,
    port: str,
    num_readings: int = 1,
    wait_time: float = 0.5,
) -> dict:
    """Request a mass reading from the bridge (may block for commercial mode).

    For Arduino mode this returns the latest cached value from the bridge's
    background thread immediately.  For commercial mode the bridge sends a
    serial command and waits up to *wait_time* seconds per reading.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.
        num_readings: Number of readings to average (commercial mode only).
        wait_time: Seconds to wait per reading (commercial mode only).

    Returns:
        Reading dict — contains ``status``, ``mass_g``, ``mass_mg``, ``port``,
        and ``method`` (``"background_reader"`` or ``"command_response"``).

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.get(
        "/balance/read",
        params={"port": port, "num_readings": num_readings, "wait_time": wait_time},
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to read balance on {port}: HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.debug("Balance read: port=%s mass_g=%s", port, result.get("mass_g"))
    return result


def get_latest_reading(client: BalanceBridgeClient, port: str) -> dict:
    """Get the latest cached reading (non-blocking, instant response).

    Designed for frequent polling from UI or automation loops.  The bridge's
    background thread keeps this value up to date as long as the balance is
    connected in Arduino mode.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.

    Returns:
        Reading dict — contains ``status``, ``mass_g``, ``mass_mg``, ``fresh``,
        ``age_seconds``, ``calibrated``, and ``calibration`` info.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.get("/balance/latest", params={"port": port})
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to get latest reading from {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    return resp.json()


def tare_balance(
    client: BalanceBridgeClient,
    port: str,
    wait: float = 5.0,
    tare_command: str = "t",
) -> dict:
    """Tare (zero) the balance.

    Sends the tare command over serial and waits *wait* seconds for the
    balance to stabilise before returning.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.
        wait: Seconds to wait for stabilisation after tare.  Defaults to ``5.0``.
        tare_command: Single-character tare command for Arduino mode.
            Defaults to ``"t"``.

    Returns:
        Tare result dict — contains ``status``, ``port``, ``message``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    payload = {"port": port, "wait": wait, "tare_command": tare_command}
    resp = client.post("/balance/tare", json=payload, timeout=int(wait) + 10)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to tare balance on {port}: HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.info("Balance tared: port=%s", port)
    return result


def get_balance_status(client: BalanceBridgeClient, port: str) -> dict:
    """Get connection status and the latest cached reading for a port.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.

    Returns:
        Status dict — contains ``connected``, ``background_reader_active``,
        ``has_data``, ``baudrate``, ``latest_mass_g``, and ``data_age_seconds``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.get("/balance/status", params={"port": port})
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to get balance status for {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    return resp.json()


def monitor_balance(
    client: BalanceBridgeClient,
    port: str,
    duration: int = 10,
    baudrate: int = 9600,
) -> dict:
    """Capture raw serial data for debugging.

    Opens a temporary serial connection if the port is not already connected
    and records all incoming bytes for *duration* seconds.  Useful for
    verifying the correct baud rate and message format.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.
        duration: Monitoring duration in seconds.  Defaults to ``10``.
        baudrate: Baud rate to use when opening a temporary connection.
            Defaults to ``9600``.

    Returns:
        Monitor dict — contains ``data_received``, ``total_messages``,
        ``readable_messages``, ``diagnosis``, and ``summary``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.get(
        "/balance/monitor",
        params={"port": port, "duration": duration, "baudrate": baudrate},
        timeout=duration + 15,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to monitor balance on {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    return resp.json()


def diagnose_balance(client: BalanceBridgeClient, port: str) -> dict:
    """Test multiple baud rates to find the correct one.

    Tries ``[9600, 115200, 57600, 38400, 19200, 4800]`` in order, collects
    2 seconds of data at each, and scores them by readable ASCII lines.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.

    Returns:
        Diagnosis dict — contains ``best_baudrate``, ``results``, ``mass_found``,
        and ``summary``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.get("/balance/diagnose", params={"port": port}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to diagnose balance on {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.info(
        "Balance diagnose complete: port=%s summary=%s", port, result.get("summary")
    )
    return result
