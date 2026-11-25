"""COMPLETE: refused while a command runs, --abort stops it, repeats succeed."""
from __future__ import annotations

import asyncio
import unittest

from processor_fakes import FakeClient, FakeMsg
from processor_fakes import message as _message

from puda.command_processor import CommandProcessor
from puda.models import (
    CommandResponse,
    CommandResponseCode,
    CommandResponseStatus,
    NATSMessage,
)


class CompleteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.processor = CommandProcessor(FakeClient(queued=3))
        await self.processor.run_manager.start_run("run-1")
        self.release = asyncio.Event()
        self.responses: list[CommandResponse] = []

        async def slow(_m: NATSMessage) -> CommandResponse:
            await self.release.wait()
            return CommandResponse(status=CommandResponseStatus.SUCCESS)

        async def capture(_msg, response, _subject) -> None:
            self.responses.append(response)

        self.processor._publish_command_response = capture  # type: ignore[method-assign]
        self.queued = asyncio.create_task(self.processor.process_queue(FakeMsg(_message("move")), slow))
        await asyncio.sleep(0.05)

    async def asyncTearDown(self) -> None:
        self.release.set()
        await asyncio.wait_for(self.queued, 1)

    async def test_plain_complete_is_refused_with_running_details(self) -> None:
        response = await self.processor._immediate_complete("run-1", _message("complete"), None)
        self.assertEqual(response.code, CommandResponseCode.EXECUTION_LOCKED)
        self.assertEqual(response.data["running"]["name"], "move")
        self.assertEqual(response.data["running"]["step_number"], 1)
        self.assertEqual(response.data["queued"], 2)
        self.assertEqual(self.processor.run_manager.get_active_run_id(), "run-1")

    async def test_abort_ends_run_at_once_and_answers_command_when_it_returns(self) -> None:
        async def stop(_m: NATSMessage) -> CommandResponse:
            # The driver abort is only started; the command keeps running.
            return CommandResponse(status=CommandResponseStatus.SUCCESS, data={"driver_abort": True})

        response = await self.processor._immediate_complete(
            "run-1", _message("complete", params={"abort": True}), stop)
        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)
        self.assertEqual(response.data["aborted"]["name"], "move")
        self.assertTrue(response.data["driver_abort"])
        self.assertNotIn("finished", response.data)
        self.assertIsNone(self.processor.run_manager.get_active_run_id())
        self.assertFalse(self.queued.done())
        self.assertEqual(self.responses, [])
        self.release.set()
        await asyncio.wait_for(self.queued, 1)
        self.assertEqual(self.responses[-1].code, CommandResponseCode.COMMAND_CANCELLED)
        self.assertEqual(self.responses[-1].message, "Stopped by complete --abort")

    async def test_repeat_complete_reports_already_completed(self) -> None:
        self.release.set()
        await asyncio.wait_for(self.queued, 1)
        first = await self.processor._immediate_complete("run-1", _message("complete"), None)
        again = await self.processor._immediate_complete("run-1", _message("complete"), None)
        self.assertEqual(first.status, CommandResponseStatus.SUCCESS)
        self.assertEqual(again.data, {"already_completed": True})
        other = await self.processor._immediate_complete("run-x", _message("complete", "run-x"), None)
        self.assertEqual(other.code, CommandResponseCode.RUN_ID_MISMATCH)

    async def test_cancel_is_unknown(self) -> None:
        async def unknown(_m: NATSMessage) -> CommandResponse:
            return CommandResponse(status=CommandResponseStatus.ERROR, code=CommandResponseCode.UNKNOWN_COMMAND)

        response = await self.processor._dispatch_immediate("cancel", "run-1", _message("cancel"), unknown)
        self.assertEqual(response.code, CommandResponseCode.UNKNOWN_COMMAND)
        self.assertEqual(self.processor.run_manager.get_active_run_id(), "run-1")


if __name__ == "__main__":
    unittest.main()
