"""Emergency stop: immediate estop latches the queue and runs the driver estop."""
from __future__ import annotations

import asyncio
import threading
import unittest

from processor_fakes import FakeClient, FakeMsg
from processor_fakes import failure as _failure
from processor_fakes import message as _message
from processor_fakes import success as _success

from puda.command import command
from puda.command_processor import CommandProcessor
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner
from puda.models import (
    CommandResponse,
    CommandResponseCode,
    CommandResponseStatus,
    ImmediateCommand,
    MachineState,
    NATSMessage,
)


class ProcessorEstopTests(unittest.IsolatedAsyncioTestCase):
    async def test_estop_latches_clears_run_and_publishes_estopped(self) -> None:
        client = FakeClient()
        processor = CommandProcessor(client)
        await processor.run_manager.start_run("run-1")

        response = await processor._dispatch_immediate(
            ImmediateCommand.ESTOP, "run-1", _message("estop"), _success
        )

        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)
        self.assertTrue(processor.is_estopped)
        self.assertIsNone(processor.run_manager.get_active_run_id())
        self.assertEqual(client.states, [{"state": MachineState.ESTOPPED, "run_id": None}])

    async def test_latch_holds_when_driver_estop_fails(self) -> None:
        processor = CommandProcessor(FakeClient())
        response = await processor._immediate_estop(_failure, _message("estop"))
        self.assertEqual(response.status, CommandResponseStatus.ERROR)
        self.assertTrue(processor.is_estopped)

    async def test_queued_commands_are_discarded_while_estopped(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor._immediate_estop(_success, _message("estop"))
        called = False

        async def handler(_m: NATSMessage) -> CommandResponse:
            nonlocal called
            called = True
            return CommandResponse(status=CommandResponseStatus.SUCCESS)

        msg = FakeMsg(_message("move"))
        await processor.process_queue(msg, handler)
        self.assertFalse(called)
        self.assertTrue(msg.termed)

    async def test_start_and_resume_are_refused_until_reset(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor._immediate_estop(_success, _message("estop"))

        start = await processor._immediate_start("run-2")
        resume = await processor._immediate_resume(_success, _message("resume"))
        self.assertEqual(start.code, CommandResponseCode.MACHINE_ESTOPPED)
        self.assertEqual(resume.code, CommandResponseCode.MACHINE_ESTOPPED)

        failed = await processor._immediate_reset(_failure, _message("reset"))
        self.assertEqual(failed.status, CommandResponseStatus.ERROR)
        self.assertTrue(processor.is_estopped)

        await processor._immediate_reset(_success, _message("reset"))
        self.assertFalse(processor.is_estopped)
        start = await processor._immediate_start("run-2")
        self.assertEqual(start.status, CommandResponseStatus.SUCCESS)


class EstopDriver:
    """Driver whose move blocks until estop releases it."""

    def __init__(self) -> None:
        self.moving = threading.Event()
        self.release = threading.Event()
        self.estop_thread: str | None = None

    @command
    def move(self) -> bool:
        self.moving.set()
        self.release.wait(5)
        return True

    @command
    def estop(self) -> dict:
        self.estop_thread = threading.current_thread().name
        self.release.set()
        return {"stopped": True}


class NoEstopDriver:
    @command
    def move(self) -> None:
        return None


async def _telemetry() -> None:
    return None


class RunnerEstopTests(unittest.IsolatedAsyncioTestCase):
    async def test_estop_runs_on_own_thread_and_cancels_running_command(self) -> None:
        driver = EstopDriver()
        runner = EdgeRunner(EdgeNatsClient(["nats://localhost:4222"], "test-1"), driver, _telemetry)

        running = asyncio.create_task(runner._handle_execute(_message("move")))
        await asyncio.get_running_loop().run_in_executor(None, driver.moving.wait, 5)

        response = await asyncio.wait_for(runner._handle_immediate(_message("estop")), 5)
        queued = await asyncio.wait_for(running, 5)

        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)
        self.assertEqual(response.data, {"stopped": True})
        self.assertTrue(driver.estop_thread.startswith("puda-estop"))
        self.assertEqual(queued.code, CommandResponseCode.COMMAND_CANCELLED)

    async def test_missing_estop_reports_no_hardware_stop(self) -> None:
        runner = EdgeRunner(
            EdgeNatsClient(["nats://localhost:4222"], "test-1"), NoEstopDriver(), _telemetry
        )
        response = await runner._handle_immediate(_message("estop"))
        self.assertEqual(response.status, CommandResponseStatus.ERROR)
        self.assertEqual(response.code, CommandResponseCode.ESTOP_NOT_SUPPORTED)
        self.assertIn("no hardware stop", response.message)

    async def test_estop_through_queue_is_rejected(self) -> None:
        driver = EstopDriver()
        runner = EdgeRunner(EdgeNatsClient(["nats://localhost:4222"], "test-1"), driver, _telemetry)
        response = await runner._handle_execute(_message("estop"))
        self.assertEqual(response.status, CommandResponseStatus.ERROR)
        self.assertIn("puda machine estop", response.message)
        self.assertIsNone(driver.estop_thread)

    async def test_published_state_stays_estopped_until_reset(self) -> None:
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        runner = EdgeRunner(client, EstopDriver(), _telemetry)
        published: list[dict] = []

        async def capture(payload: dict) -> None:
            published.append(payload)

        client.publish_state = capture  # type: ignore[method-assign]
        client.commands._is_estopped = True
        await runner._publish_state(MachineState.IDLE)
        await runner._publish_state(MachineState.OFFLINE)
        self.assertEqual(
            [p["state"] for p in published], [MachineState.ESTOPPED, MachineState.OFFLINE]
        )


if __name__ == "__main__":
    unittest.main()
