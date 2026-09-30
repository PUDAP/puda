"""Host vitals published by EdgeRunner on puda.{machine_id}.tlm.health."""
from __future__ import annotations

from typing import Any

import psutil

_TEMPERATURE_SENSORS = ("coretemp", "cpu_thermal", "k10temp", "acpitz")


def _cpu_temperature() -> float | None:
    if not hasattr(psutil, "sensors_temperatures"):
        return None
    try:
        all_temps = psutil.sensors_temperatures() or {}
    except Exception:
        return None
    for name in _TEMPERATURE_SENSORS:
        readings = all_temps.get(name)
        if readings:
            return readings[0].current
    return None


def read_host_health() -> dict[str, Any]:
    """Return CPU percent, memory percent, and CPU temperature (or None)."""
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "mem": psutil.virtual_memory().percent,
        "temp": _cpu_temperature(),
    }
