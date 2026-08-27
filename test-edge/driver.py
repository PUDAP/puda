"""
In-memory test machine driver.

No hardware is required. Public methods decorated with ``@command`` are advertised
on NATS and can be invoked through the PUDA CLI or a protocol file.
"""

from __future__ import annotations

import logging
import time

from puda import command

logger = logging.getLogger(__name__)


class Driver:
    def __init__(self, command_delay: float = 0.0):
        self._command_delay = max(0.0, command_delay)
        self._position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._homed = False
        self._last_error: str | None = None

    def _simulate_work(self) -> None:
        if self._command_delay:
            time.sleep(self._command_delay)

    @command
    def shutdown(self) -> bool:
        """Release simulated resources. Used internally on edge restart, not a remote command."""
        logger.info("Test driver shutdown")
        return True

    @command
    def get_position(self) -> dict[str, float]:
        """Current simulated cartesian position (telemetry only)."""
        return dict(self._position)

    def snapshot(self) -> dict:
        """Extra fields merged into MACHINE_STATE KV updates."""
        return {
            "homed": self._homed,
            "position": self.get_position(),
            "last_error": self._last_error,
        }

    @command
    def home(self) -> dict:
        """
        Home the machine. Used by ``puda machine home fake``.

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
    def reset(self) -> dict:
        """
        Software reset. Used by ``puda machine reset fake``.

        Returns:
            dict: Reset confirmation
        """
        self._simulate_work()
        self._position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._homed = False
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
    def move(self, x: float, y: float, z: float) -> dict:
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
    def echo(self, message: str = "") -> dict:
        """
        Echo a string back. Useful for round-trip command tests.

        Args:
            message: Payload to return

        Returns:
            dict: The same message
        """
        self._simulate_work()
        return {"message": message}

    @command
    def wait(self, seconds: float = 1.0) -> dict:
        """
        Block for ``seconds``. Use this to test BUSY state, locks, and cancel.

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

    @command
    def get_status(self) -> dict:
        """Return the current simulated machine snapshot."""
        return self.snapshot()
