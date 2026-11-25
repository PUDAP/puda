"""Lifecycle hooks are found by name, never advertised or queued as commands."""
from __future__ import annotations

import unittest

from processor_fakes import message

from puda import LIFECYCLE_HOOKS, LifecycleHookError
from puda.command import build_command_catalog, command, require_command_names, resolve_hook_names
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner
from puda.models import CommandResponseCode, CommandResponseStatus


class Driver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @command
    def move(self) -> dict:
        """Move."""
        return {"moved": True}

    def pause(self) -> dict:
        self.calls.append("pause")
        return {"paused": True}

    def estop(self) -> None:
        self.calls.append("estop")


class DecoratedHookDriver:
    @command
    def move(self) -> None:
        """Move."""

    @command
    def estop(self) -> None:
        """Stop."""

    @command
    def reset(self) -> None:
        """Reset."""


def _runner(driver: object) -> EdgeRunner:
    return EdgeRunner(EdgeNatsClient(["nats://localhost:4222"], "test-1"), driver)


class HookDiscoveryTests(unittest.TestCase):
    def test_hooks_are_found_by_name_and_not_advertised(self) -> None:
        driver = Driver()
        self.assertEqual(resolve_hook_names(driver), {"pause", "estop"})
        self.assertEqual(require_command_names(driver), {"move"})
        text, catalog = build_command_catalog(driver)
        self.assertEqual([entry["name"] for entry in catalog], ["move"])
        self.assertNotIn("pause", text)
        self.assertEqual(_runner(driver).hooks, {"pause", "estop"})

    def test_decorated_hook_fails_at_startup_naming_the_methods(self) -> None:
        with self.assertRaises(LifecycleHookError) as raised:
            _runner(DecoratedHookDriver())
        self.assertIn("DecoratedHookDriver.estop, DecoratedHookDriver.reset", str(raised.exception))
        self.assertIn("Remove @command", str(raised.exception))

    def test_hook_names(self) -> None:
        self.assertEqual(set(LIFECYCLE_HOOKS), {"pause", "resume", "reset", "estop", "abort", "shutdown"})


class HookDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_immediate_pause_calls_hook_and_returns_its_data(self) -> None:
        driver = Driver()
        response = await _runner(driver)._handle_immediate(message("pause", run_id=""))
        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)
        self.assertEqual(response.data, {"paused": True})
        self.assertEqual(driver.calls, ["pause"])

    async def test_missing_hook_succeeds(self) -> None:
        response = await _runner(Driver())._handle_immediate(message("resume", run_id=""))
        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)

    async def test_hooks_cannot_be_queued(self) -> None:
        runner = _runner(Driver())
        for name, expected in [
            ("pause", "use puda machine pause"),
            ("ESTOP", "use puda machine estop"),
            ("abort", "use puda machine complete --abort"),
            ("shutdown", "not remotely callable"),
        ]:
            response = await runner._handle_execute(message(name))
            self.assertEqual(response.code, CommandResponseCode.EXECUTION_ERROR, name)
            self.assertIn(expected, response.message or "")

    async def test_hook_names_are_not_immediate_driver_commands(self) -> None:
        response = await _runner(Driver())._handle_immediate(message("shutdown", run_id=""))
        self.assertEqual(response.code, CommandResponseCode.UNKNOWN_COMMAND)


if __name__ == "__main__":
    unittest.main()
