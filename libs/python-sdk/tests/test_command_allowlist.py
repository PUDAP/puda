"""Tests for @command-based remote command discovery."""
from __future__ import annotations

import inspect
import unittest
import unittest.mock

from puda.command import (
    SDK_UPDATE_ERROR,
    build_command_catalog,
    command,
    get_safety,
    iter_command_methods,
    require_command_names,
    resolve_command_names,
    safety,
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


class SafetyDriver(SerialDevice):
    @command
    @safety("Collision risk if the deck is occupied.")
    def move(self, x: float) -> None:
        """Move the gantry."""

    @command
    @safety(
        "Heats the plate.",
        hazards=["thermal"],
        requires="Clamp must be closed before heating.",
        forbidden_when="Do not heat if the lid is open.",
        confirm=False,
    )
    def set_temp(self, temperature: int) -> None:
        """Hold temperature."""

    @safety("Not a remote command.")
    def write(self, data: str) -> bool:
        return True

    @command
    def home(self) -> None:
        """No safety tag."""

    @command
    @safety("Collision risk.")
    def move_to(self, x: float) -> dict:
        """
        Move to an absolute position.

        Args:
            x: Target X
        """
        return {}


class SafetyDecoratorTest(unittest.TestCase):
    def test_default_confirm_is_true(self) -> None:
        meta = get_safety(SafetyDriver.move)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.summary, "Collision risk if the deck is occupied.")
        self.assertIsNone(meta.requires)
        self.assertIsNone(meta.forbidden_when)
        self.assertTrue(meta.confirm)

    def test_prose_fields_and_confirm_override(self) -> None:
        meta = get_safety(SafetyDriver.set_temp)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.hazards, ("thermal",))
        self.assertEqual(meta.requires, "Clamp must be closed before heating.")
        self.assertEqual(meta.forbidden_when, "Do not heat if the lid is open.")
        self.assertFalse(meta.confirm)

    def test_safety_without_command_is_not_advertised(self) -> None:
        names = resolve_command_names(SafetyDriver())
        self.assertEqual(names, frozenset({"move", "set_temp", "home", "move_to"}))
        self.assertNotIn("write", names)
        self.assertIsNotNone(get_safety(SafetyDriver.write))

    def test_either_decorator_order_works(self) -> None:
        @safety("Home before jogging.")
        @command
        def jog(self) -> None:
            pass

        self.assertTrue(jog.__puda_command__)
        self.assertEqual(get_safety(jog).summary, "Home before jogging.")
        self.assertTrue(get_safety(jog).confirm)

    def test_bare_safety_requires_summary(self) -> None:
        with self.assertRaises(TypeError):

            @safety
            def broken(self) -> None:
                pass

        with self.assertRaises(ValueError):

            @safety("   ")
            def empty(self) -> None:
                pass

    def test_catalog_includes_safety_text_and_structured_entry(self) -> None:
        text, catalog = build_command_catalog(SafetyDriver())
        self.assertIn("move(self, x:", text)
        self.assertIn("    Move the gantry.", text)
        self.assertLess(
            text.index("    Move the gantry."),
            text.index("    safety:"),
        )
        self.assertIn("    safety:", text)
        self.assertIn("        Collision risk if the deck is occupied.", text)
        self.assertIn("        confirm: true", text)
        self.assertNotIn("Safety-severity:", text)
        self.assertIn("        Heats the plate.", text)
        self.assertIn("        hazards: thermal", text)
        self.assertIn("        requires: Clamp must be closed before heating.", text)
        self.assertIn("        forbidden_when: Do not heat if the lid is open.", text)
        self.assertIn("        confirm: false", text)
        self.assertNotIn("write(", text)

        by_name = {entry["name"]: entry for entry in catalog}
        self.assertEqual(
            by_name["move"]["safety"],
            {
                "summary": "Collision risk if the deck is occupied.",
                "hazards": [],
                "requires": None,
                "forbidden_when": None,
                "confirm": True,
            },
        )
        self.assertIsNone(by_name["home"]["safety"])
        self.assertFalse(by_name["set_temp"]["safety"]["confirm"])
        move_to = text[text.index("move_to(") :]
        self.assertLess(move_to.index("    Move to an absolute position."), move_to.index("    safety:"))
        self.assertLess(move_to.index("        Collision risk."), move_to.index("    Args:"))


if __name__ == "__main__":
    unittest.main()
