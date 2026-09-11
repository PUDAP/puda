"""
In-memory test machine driver.

No hardware is required. Public methods decorated with ``@command`` are advertised
on NATS and can be invoked through the PUDA CLI or a protocol file.

Command coverage:
- lifecycle: ``shutdown``, ``home``, ``reset``, ``pause``, ``resume``, ``cancel``
- no safety: readbacks and primitive round-trips
- safety, ``confirm=False``: ``set_heater``
- safety, ``confirm=True``: ``move_to``
- JSON primitives on input and output: str, int, float, bool, bytes, dict, list,
  any, null/optional, unions, nested objects/arrays, and ``Dict[str, str]``
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from puda import command, safety

logger = logging.getLogger(__name__)


class Driver:
    """Software-only PUDA test machine. Commands are simulated in memory; no hardware is required."""

    def __init__(self, command_delay: float = 0.0):
        self._command_delay = max(0.0, command_delay)
        self._position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._homed = False
        self._heater_celsius = 0.0
        self._last_error: str | None = None

    def _simulate_work(self) -> None:
        if self._command_delay:
            time.sleep(self._command_delay)

    def snapshot(self) -> dict:
        """Extra fields merged into MACHINE_STATE KV updates."""
        return {
            "homed": self._homed,
            "position": self.get_position(),
            "heater_celsius": self._heater_celsius,
            "last_error": self._last_error,
        }

    @command
    def shutdown(self) -> bool:
        """
        Release simulated resources. Used internally on edge restart, not a remote command.

        Returns:
            bool: Always True
        """
        logger.info("Test driver shutdown")
        return True

    @command
    def get_position(self) -> dict[str, float]:
        """
        Current simulated cartesian position (telemetry only).

        Returns:
            dict[str, float]: Keys x, y, z
        """
        return dict(self._position)

    @command
    def get_status(self) -> dict:
        """
        Return the current simulated machine snapshot.

        Returns:
            dict: Homed flag, position, heater setpoint, last error
        """
        return self.snapshot()

    @command
    def home(self) -> dict:
        """
        Home the machine. Used by ``puda machine home <machine-id>``.

        Returns:
            dict: Homed flag and origin position
        """
        self._simulate_work()
        self._position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._homed = True
        self._last_error = None
        logger.info("Homed to origin")
        return {"homed": True, "position": self.get_position()}

    @command
    @safety(
        summary="Collision risk from unhomed motion or an occupied workspace.",
        hazards=["collision"],
        requires="Machine must just have been homed.",
        forbidden_when="Do not move if the workspace is occupied or human movement is detected.",
        confirm=True,
    )
    def move_to(self, x: float, y: float, z: float) -> dict:
        """
        Move to an absolute simulated position.

        Args:
            x: Target X
            y: Target Y
            z: Target Z

        Returns:
            dict: New position
        """
        self._simulate_work()
        self._position = {"x": float(x), "y": float(y), "z": float(z)}
        logger.info("Moved to %s", self._position)
        return {"position": self.get_position()}

    @command
    @safety(
        summary="Thermal hazard from simulated heater power.",
        hazards=["thermal"],
        requires="Workspace must be clear of flammable material.",
        forbidden_when="Do not heat if a thermal interlock is active.",
    )
    def set_heater(self, celsius: float) -> dict:
        """
        Set the simulated heater temperature. Advisory safety only; no operator confirm.

        Args:
            celsius: Target temperature in Celsius

        Returns:
            dict: Applied setpoint
        """
        self._simulate_work()
        self._heater_celsius = float(celsius)
        logger.info("Heater setpoint %s C", self._heater_celsius)
        return {"heater_celsius": self._heater_celsius}

    @command
    def reset(self) -> dict:
        """
        Software reset. Used by ``puda machine reset <machine-id>``.

        Returns:
            dict: Reset confirmation
        """
        self._simulate_work()
        self._position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._homed = False
        self._heater_celsius = 0.0
        self._last_error = None
        logger.info("Reset test machine")
        return {"reset": True, "position": self.get_position()}

    @command
    def pause(self) -> dict:
        """Acknowledge queue pause. Queue gating is handled by the edge client."""
        return {"paused": True}

    @command
    def resume(self) -> dict:
        """Acknowledge queue resume. Queue gating is handled by the edge client."""
        return {"paused": False}

    @command
    def cancel(self) -> dict:
        """Acknowledge cancel. Run teardown is handled by the edge client."""
        return {"cancelled": True}

    @command
    def echo(self, message: str = "") -> dict:
        """
        Echo a string inside a dict. Useful for round-trip command tests.

        Args:
            message: Payload to return

        Returns:
            dict: The same message
        """
        self._simulate_work()
        return {"message": message}

    @command
    def echo_str(self, value: str) -> str:
        """
        Round-trip a string.

        Args:
            value: String payload

        Returns:
            str: The same value
        """
        return value

    @command
    def echo_int(self, value: int) -> int:
        """
        Round-trip an integer.

        Args:
            value: Integer payload

        Returns:
            int: The same value
        """
        return int(value)

    @command
    def echo_float(self, value: float) -> float:
        """
        Round-trip a float.

        Args:
            value: Float payload

        Returns:
            float: The same value
        """
        return float(value)

    @command
    def echo_bool(self, enabled: bool) -> bool:
        """
        Round-trip a boolean.

        Args:
            enabled: Boolean payload

        Returns:
            bool: The same value
        """
        return bool(enabled)

    @command
    def echo_bytes(self, blob: bytes) -> str:
        """
        Accept bytes (JSON string) and return a hex string so the response stays JSON.

        Args:
            blob: Bytes payload. Protocol JSON sends this as a string.

        Returns:
            str: UTF-8 hex encoding of the payload
        """
        if isinstance(blob, str):
            data = blob.encode("utf-8")
        else:
            data = bytes(blob)
        return data.hex()

    @command
    def echo_list(self, values: list[int]) -> list[int]:
        """
        Round-trip a list of integers.

        Args:
            values: Integer array

        Returns:
            list[int]: The same values
        """
        return [int(item) for item in values]

    @command
    def echo_dict(self, layout: dict[str, str]) -> dict[str, str]:
        """
        Round-trip a string-to-string object.

        Args:
            layout: Object whose keys and values are strings

        Returns:
            dict[str, str]: The same object
        """
        return {str(key): str(value) for key, value in layout.items()}

    @command
    def echo_any(self, payload: Any) -> Any:
        """
        Round-trip any JSON value. Protocol validate accepts Any without type-checking the payload.

        Args:
            payload: Any JSON value

        Returns:
            Any: The same value
        """
        return payload

    @command
    def echo_optional(self, note: str | None = None) -> str | None:
        """
        Round-trip a nullable string. Omit the param or pass JSON null.

        Args:
            note: Optional string, or null

        Returns:
            str | None: The same value
        """
        return note

    @command
    def echo_union(self, value: int | float) -> int | float:
        """
        Round-trip a number that may be int or float.

        Args:
            value: Integer or floating-point number

        Returns:
            int | float: The same value
        """
        return value

    @command
    def echo_nested(self, points: dict[str, list[float]]) -> dict[str, list[float]]:
        """
        Round-trip nested dict[str, list[float]].

        Args:
            points: Named series of floats

        Returns:
            dict[str, list[float]]: The same object
        """
        return {str(key): [float(item) for item in items] for key, items in points.items()}

    @command
    def echo_records(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """
        Round-trip a list of string objects.

        Args:
            rows: Array of objects with string values

        Returns:
            list[dict[str, str]]: The same rows
        """
        return [{str(key): str(value) for key, value in row.items()} for row in rows]

    @command
    def echo_mixed(
        self,
        name: str,
        count: int,
        enabled: bool,
        tags: list[str],
        meta: dict[str, str],
    ) -> dict:
        """
        Round-trip several primitives in one command.

        Args:
            name: Label
            count: Integer count
            enabled: Flag
            tags: String array
            meta: String object

        Returns:
            dict: The same fields
        """
        return {
            "name": name,
            "count": int(count),
            "enabled": bool(enabled),
            "tags": [str(tag) for tag in tags],
            "meta": {str(key): str(value) for key, value in meta.items()},
        }

    @command
    def load_layout(self, layout: Dict[str, str]) -> dict[str, str | None]:
        """
        Accept typing.Dict[str, str] (same JSON object as dict[str, str]).

        Empty string values are stored as null so the return type is dict[str, str | None].

        Args:
            layout: Slot name to labware name

        Returns:
            dict[str, str | None]: Loaded layout
        """
        loaded: dict[str, str | None] = {
            str(key): (str(value) if value else None) for key, value in layout.items()
        }
        logger.info("Loaded layout %s", loaded)
        return loaded

    @command
    def wait(self, seconds: float = 1.0) -> dict:
        """
        Block for ``seconds``. Use this to test BUSY state, locks, and cancel.

        Protocols should use the CLI ``wait`` builtin instead of this machine command.

        Args:
            seconds: How long to sleep

        Returns:
            dict: Duration actually waited
        """
        duration = max(0.0, float(seconds))
        time.sleep(duration)
        return {"waited": duration}

    @command
    def fail(self, message: str = "simulated failure") -> None:
        """
        Raise so the edge returns an EXECUTION_ERROR. Use this to test error paths.

        Args:
            message: Error text returned to the caller
        """
        self._simulate_work()
        self._last_error = message
        raise RuntimeError(message)
