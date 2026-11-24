"""Pause holds the queue; resume runs held commands in order."""
from __future__ import annotations

import asyncio
import unittest

from processor_fakes import FakeClient, FakeMsg
from processor_fakes import message as _message
from processor_fakes import success as _success

from puda.command_processor import CommandProcessor
from puda.models import (
    CommandResponse,
    CommandResponseStatus,
    NATSMessage,
)


class PauseHoldsQueueTests(unittest.IsolatedAsyncioTestCase):
    async def _paused_processor(self) -> CommandProcessor:
        processor = CommandProcessor(FakeClient())
        await processor.run_manager.start_run("run-1")
        await processor._immediate_pause(_message("pause"), _success)
        return processor

    async def test_pull_loop_blocks_while_paused(self) -> None:
        processor = await self._paused_processor()
        waiter = asyncio.create_task(processor.wait_until_runnable())
        await asyncio.sleep(0.05)
        self.assertFalse(waiter.done())

        await processor._immediate_resume(_success, _message("resume"))
        await asyncio.wait_for(waiter, 1)

    async def test_delivered_command_is_held_then_runs_on_resume(self) -> None:
        processor = await self._paused_processor()
        executed: list[str] = []

        async def handler(message: NATSMessage) -> CommandResponse:
            executed.append(message.command.name)
            return CommandResponse(status=CommandResponseStatus.SUCCESS)

        msg = FakeMsg(_message("move"))
        task = asyncio.create_task(processor.process_queue(msg, handler))
        await asyncio.sleep(0.05)
        self.assertEqual(executed, [])
        self.assertFalse(msg.acked or msg.termed)

        await processor._immediate_resume(_success, _message("resume"))
        await asyncio.wait_for(task, 1)
        self.assertEqual(executed, ["move"])
        self.assertTrue(msg.acked)
        self.assertFalse(msg.termed)

    async def test_estop_discards_held_command(self) -> None:
        processor = await self._paused_processor()
        called = False

        async def handler(_m: NATSMessage) -> CommandResponse:
            nonlocal called
            called = True
            return CommandResponse(status=CommandResponseStatus.SUCCESS)

        msg = FakeMsg(_message("move"))
        task = asyncio.create_task(processor.process_queue(msg, handler))
        await asyncio.sleep(0.05)
        await processor._immediate_estop(_success, _message("estop"))
        await asyncio.wait_for(task, 1)
        self.assertFalse(called)
        self.assertTrue(msg.termed)

    async def test_estop_releases_pull_loop_so_backlog_is_discarded(self) -> None:
        processor = await self._paused_processor()
        await processor._immediate_estop(_success, _message("estop"))
        await asyncio.wait_for(processor.wait_until_runnable(), 1)

    async def test_reset_after_estop_keeps_queue_paused(self) -> None:
        processor = await self._paused_processor()
        await processor._immediate_estop(_success, _message("estop"))
        await processor._immediate_reset(_success, _message("reset"))
        self.assertTrue(processor.is_paused)
        waiter = asyncio.create_task(processor.wait_until_runnable())
        await asyncio.sleep(0.05)
        self.assertFalse(waiter.done())
        waiter.cancel()

    async def test_pause_and_resume_report_the_active_run(self) -> None:
        processor = await self._paused_processor()
        self.assertEqual(processor._client.states[-1], {"state": "paused", "run_id": "run-1"})
        await processor._immediate_resume(_success, _message("resume", run_id=""))
        self.assertEqual(processor._client.states[-1], {"state": "idle", "run_id": "run-1"})

    async def test_pause_without_run_reports_null_not_header_value(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor._immediate_pause(_message("pause", run_id=""), _success)
        self.assertEqual(processor._client.states[-1], {"state": "paused", "run_id": None})


if __name__ == "__main__":
    unittest.main()
