"""Calibration controllers for the Balance Bridge API.

Calibration converts raw ADC counts from the load cell to grams using the
linear formula::

    grams = (raw_adc - intercept) / slope

The bundled file ``100g load cell calibration.csv`` (located in this
package directory) contains multi-point measurements for a 100 g load cell.
:func:`load_default_calibration` reads that file, computes a linear fit
locally, and pushes the result to the bridge — so the driver owns the
calibration data and the bridge never needs a hard-coded fallback.

Each public function maps 1-to-1 to a ``/balance/calibration/*`` endpoint on
the bridge and raises :class:`RuntimeError` on failure.

Typical usage::

    from balance_driver.core.http_client import BalanceBridgeClient
    from balance_driver.controllers import calibration as cal_ctrl

    client = BalanceBridgeClient()
    cal_ctrl.load_default_calibration(client, port="COM8")
    cal_ctrl.enable_calibration(client, port="COM8", enabled=True)
"""

from __future__ import annotations

import importlib.resources as _pkg_resources
import logging

from balance_driver.core.http_client import BalanceBridgeClient

logger = logging.getLogger(__name__)

_CSV_FILENAME = "100g load cell calibration.csv"


# ---------------------------------------------------------------------------
# Internal helpers — CSV parsing and linear regression
# ---------------------------------------------------------------------------


def _read_bundled_csv() -> str:
    """Return the contents of the bundled load-cell calibration CSV as a string."""
    pkg = _pkg_resources.files("balance_driver.controllers")
    return pkg.joinpath(_CSV_FILENAME).read_text(encoding="utf-8")


def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """Ordinary least-squares linear regression.

    Args:
        x: Independent variable values (e.g. weight in grams).
        y: Dependent variable values (e.g. raw ADC readings).

    Returns:
        ``(slope, intercept)`` such that ``y ≈ slope * x + intercept``.

    Raises:
        ValueError: If fewer than 2 points are supplied or all x values are
            identical.
    """
    n = len(x)
    if n < 2:
        raise ValueError("Need at least 2 points for linear regression.")
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        raise ValueError("Cannot compute regression — all x values are identical.")
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def _parse_calibration_csv(csv_content: str) -> tuple[float, float]:
    """Parse calibration CSV and return ``(slope, intercept)`` via linear fit.

    Expected CSV columns: ``Calibration weight (g)``, ``Mean``, …

    Args:
        csv_content: Raw CSV text including the header row.

    Returns:
        ``(slope, intercept)`` where ``raw_adc = slope * grams + intercept``.

    Raises:
        ValueError: If fewer than 2 valid rows are found.
    """
    lines = csv_content.strip().splitlines()
    grams: list[float] = []
    raw_values: list[float] = []
    for line in lines[1:]:  # skip header
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                grams.append(float(parts[0].strip()))
                raw_values.append(float(parts[1].strip()))
            except ValueError:
                continue
    if len(grams) < 2:
        raise ValueError("CSV must contain at least 2 valid calibration rows.")
    return _linear_regression(grams, raw_values)


def get_bundled_calibration() -> tuple[float, float]:
    """Compute and return ``(slope, intercept)`` from the bundled CSV.

    This is a pure local operation — no bridge connection required.  Useful
    for inspecting the calibration values or pre-computing them before
    connecting.

    Returns:
        ``(slope, intercept)`` derived from ``100g load cell calibration.csv``.

    Raises:
        RuntimeError: If the bundled CSV cannot be read or parsed.
    """
    try:
        csv_content = _read_bundled_csv()
        slope, intercept = _parse_calibration_csv(csv_content)
        logger.debug(
            "Bundled calibration: slope=%.4f intercept=%.4f", slope, intercept
        )
        return slope, intercept
    except Exception as exc:
        raise RuntimeError(f"Failed to read bundled calibration CSV: {exc}") from exc


def set_calibration(
    client: BalanceBridgeClient,
    port: str,
    slope: float,
    intercept: float = 0.0,
) -> dict:
    """Set ADC-to-grams calibration parameters for a port and enable it.

    Formula: ``grams = (raw_adc - intercept) / slope``

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.
        slope: ADC counts per gram.
        intercept: ADC offset at zero grams.  Defaults to ``0.0``.

    Returns:
        Result dict — contains ``status``, ``port``, ``slope``, ``intercept``,
        ``enabled``, and ``message``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    payload = {"port": port, "slope": slope, "intercept": intercept}
    resp = client.post("/balance/calibration/set", json=payload)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to set calibration for {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.info(
        "Calibration set: port=%s slope=%s intercept=%s", port, slope, intercept
    )
    return result


def get_calibration(client: BalanceBridgeClient, port: str) -> dict:
    """Get the current calibration data for a port.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.

    Returns:
        Calibration dict — contains ``port``, ``slope``, ``intercept``,
        ``calibrated``, ``source``, and ``formula``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.get("/balance/calibration/get", params={"port": port})
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to get calibration for {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    return resp.json()


def load_calibration_csv(
    client: BalanceBridgeClient,
    port: str,
    csv_data: str,
) -> dict:
    """Load calibration from a CSV string and enable it.

    The bridge performs a linear regression on the supplied data points to
    compute ``slope`` and ``intercept``.

    Expected CSV format::

        Calibration weight (g),Mean,Stdev,% Error
        100,1744626.405,56.24,0.003
        50,872057.452,31.52,0.004

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.
        csv_data: Full CSV content as a string (header row + data rows).

    Returns:
        Result dict — contains ``status``, ``port``, ``slope``, ``intercept``,
        ``enabled``, and ``message``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response or cannot parse
            the CSV.
    """
    resp = client.post(
        "/balance/calibration/load_csv",
        params={"port": port, "csv_data": csv_data},
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to load CSV calibration for {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.info(
        "CSV calibration loaded: port=%s slope=%.4f", port, result.get("slope", 0)
    )
    return result


def load_default_calibration(client: BalanceBridgeClient, port: str) -> dict:
    """Load the bundled 100 g load-cell calibration and push it to the bridge.

    Reads ``100g load cell calibration.csv`` from the package, computes a
    linear fit locally (``raw_adc = slope * grams + intercept``), and sends
    the resulting parameters to the bridge via
    ``POST /balance/calibration/set``.  This makes the driver the single
    source of truth for calibration data.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.

    Returns:
        Result dict — contains ``status``, ``port``, ``slope``, ``intercept``,
        ``enabled``, and ``message``.

    Raises:
        RuntimeError: If the CSV cannot be read/parsed or the bridge returns a
            non-200 response.
    """
    slope, intercept = get_bundled_calibration()
    logger.info(
        "Pushing bundled calibration to bridge: port=%s slope=%.4f intercept=%.4f",
        port,
        slope,
        intercept,
    )
    return set_calibration(client, port=port, slope=slope, intercept=intercept)


def test_calibration(
    client: BalanceBridgeClient,
    port: str,
    raw_value: float,
) -> dict:
    """Convert a raw ADC value to grams using the current calibration.

    Useful for verifying that the calibration parameters produce the expected
    output before live measurements.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port (used to look up calibration).
        raw_value: Raw ADC integer to convert.

    Returns:
        Result dict — contains ``raw_value``, ``mass_g``, ``mass_mg``, and
        the ``calibration`` parameters used.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.get(
        "/balance/calibration/test",
        params={"port": port, "raw_value": raw_value},
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to test calibration for {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    return resp.json()


def enable_calibration(
    client: BalanceBridgeClient,
    port: str,
    enabled: bool = True,
) -> dict:
    """Enable or disable ADC-to-grams calibration for a port.

    When disabled the bridge returns raw ADC counts instead of converted
    grams.  Useful for inspecting raw sensor output during setup.

    Args:
        client: Active :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port.
        enabled: ``True`` to enable calibration, ``False`` to disable.

    Returns:
        Result dict — contains ``status``, ``port``, ``enabled``, and
        ``message``.

    Raises:
        RuntimeError: If the bridge returns a non-200 response.
    """
    resp = client.post(
        "/balance/calibration/enable",
        params={"port": port, "enabled": enabled},
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to {'enable' if enabled else 'disable'} calibration for {port}: "
            f"HTTP {resp.status_code} — {resp.text}"
        )
    result = resp.json()
    logger.info(
        "Calibration %s: port=%s", "enabled" if enabled else "disabled", port
    )
    return result
