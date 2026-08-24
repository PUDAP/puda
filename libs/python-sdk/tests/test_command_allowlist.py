"""Tests for @command-based remote command discovery."""
from __future__ import annotations

import inspect
import unittest
import unittest.mock

from puda.command import (
    SDK_UPDATE_ERROR,
    command,
    iter_command_methods,
    require_command_names,
    resolve_command_names,
)
from puda.edge_runner import EdgeRunner, _validate_handler
from puda.models import CommandResponseCode, CommandResponseStatus


class SerialDevice:
    def connect(self) -> None:
        """Open the serial port."""

    def disconnect(self) -> None:
        """Close the serial port."""

    def read(self) -> str:
        return ""

    def write(self, data: str) -> bool:
        return True

    def query(self, data: str) -> str:
        return data

    def start_stream(self) -> None:
        """Start streaming serial data."""

    def stop_stream(self) -> None:
        """Stop streaming serial data."""


class BioShake(SerialDevice):
    @command
    def shake(self, speed: int, duration: int) -> None:
        """Shake at speed RPM for duration seconds."""

    @command
    def set_temp(self, temperature: int, duration: int) -> None:
        """Hold temperature for duration seconds."""

    @command
    def home(self) -> None:
        """Move to the home position."""

    @command
    def open_clamp(self) -> bool:
        return True

    @command
    def close_clamp(self) -> bool:
        return True

    def get_position(self) -> dict[str, float]:
        return {"speed": 0.0}


class PlainDriver(SerialDevice):
    def shake(self) -> None:
        pass


def _legacy_public_methods(driver: object) -> frozenset[str]:
    """Reproduce pre-allowlist EdgeRunner command discovery."""
    cls = type(driver)
    return frozenset(
        name
        for name, func in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    )


def _legacy_validate_handler(driver: object, command_name: str):
    """Reproduce pre-allowlist EdgeRunner dispatch."""
    handler = getattr(driver, command_name, None)
    if not callable(handler) or command_name.startswith("_"):
        return None
    return handler


class CommandDecoratorTest(unittest.TestCase):
    def test_decorator_excludes_inherited_serial_methods(self) -> None:
        allowed = resolve_command_names(BioShake())
        self.assertEqual(
            allowed,
            frozenset({"shake", "set_temp", "home", "open_clamp", "close_clamp"}),
        )
        self.assertNotIn("read", allowed)
        self.assertNotIn("write", allowed)
        self.assertNotIn("query", allowed)
        self.assertNotIn("disconnect", allowed)
        self.assertNotIn("start_stream", allowed)
        self.assertNotIn("get_position", allowed)

    def test_undecorated_driver_requires_sdk_update(self) -> None:
        driver = PlainDriver()
        self.assertEqual(resolve_command_names(driver), frozenset())
        with self.assertRaises(RuntimeError) as raised:
            require_command_names(driver)
        self.assertEqual(str(raised.exception), "Update SDK to 0.0.17")
        self.assertEqual(str(raised.exception), SDK_UPDATE_ERROR)

        handler, error = _validate_handler(driver, "shake", frozenset())
        self.assertIsNone(handler)
        self.assertIsNotNone(error)
        self.assertEqual(error.status, CommandResponseStatus.ERROR)
        self.assertEqual(error.message, "Update SDK to 0.0.17")

        nats_client = unittest.mock.Mock()
        with self.assertRaises(RuntimeError) as raised:
            EdgeRunner(
                nats_client=nats_client,
                machine_driver=driver,
                telemetry_handler=unittest.mock.AsyncMock(),
            )
        self.assertEqual(str(raised.exception), "Update SDK to 0.0.17")

    def test_dispatch_rejects_low_level_ops(self) -> None:
        driver = BioShake()
        allowed = resolve_command_names(driver)
        handler, error = _validate_handler(driver, "write", allowed)
        self.assertIsNone(handler)
        self.assertIsNotNone(error)
        self.assertEqual(error.status, CommandResponseStatus.ERROR)
        self.assertEqual(error.code, CommandResponseCode.UNKNOWN_COMMAND)

        handler, error = _validate_handler(driver, "shake", allowed)
        self.assertTrue(callable(handler))
        self.assertIsNone(error)

    def test_published_catalog_omits_serial_ops(self) -> None:
        names = [name for name, _ in iter_command_methods(BioShake())]
        self.assertEqual(
            names,
            ["close_clamp", "home", "open_clamp", "set_temp", "shake"],
        )

    def test_decorator_is_ignored_by_older_sdk(self) -> None:
        driver = BioShake()
        legacy_commands = _legacy_public_methods(driver)

        self.assertIn("shake", legacy_commands)
        self.assertIn("write", legacy_commands)
        self.assertIn("read", legacy_commands)
        self.assertIn("query", legacy_commands)
        self.assertIn("disconnect", legacy_commands)
        self.assertIn("start_stream", legacy_commands)
        self.assertIsNotNone(_legacy_validate_handler(driver, "write"))
        self.assertIsNotNone(_legacy_validate_handler(driver, "query"))

        current_commands = resolve_command_names(driver)
        self.assertIn("shake", current_commands)
        self.assertNotIn("write", current_commands)
        handler, error = _validate_handler(driver, "write", current_commands)
        self.assertIsNone(handler)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, CommandResponseCode.UNKNOWN_COMMAND)


if __name__ == "__main__":
    unittest.main()
