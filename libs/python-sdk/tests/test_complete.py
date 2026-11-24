"""COMPLETE: refused while a command runs, --abort stops it, repeats succeed."""
from __future__ import annotations

import asyncio
import unittest
from typing import Any

from puda.command_processor import CommandProcessor
from puda.models import (
    CommandRequest,
    CommandResponse,
    CommandResponseCode,
    CommandResponseStatus,
    MessageHeader,
    MessageType,
    NATSMessage,
)


def _message(name: str, run_id: str | None = "run-1", params: dict | None = None) -> NATSMessage:
    return NATSMessage(
        header=MessageHeader(message_type=MessageType.COMMAND, user_id="u", username="u",
                             machine_id="test-1", run_id=run_id),
        command=CommandRequest(name=name, step_number=1, machine_id="test-1", params=params or {}),
    )


class PlainEncryption:
    def open_payload(self, _subject: str, data: bytes) -> bytes:
        return data


class FakeClient:
    def __init__(self) -> None:
        self.machine_id = "test-1"
        self.states: list[dict[str, Any]] = []
        self.encryption = PlainEncryption()
        self.js = None
        self.response_queue = "q"
        self.response_immediate = "i"
        self.published: list[tuple[str, CommandResponse]] = []

    async def publish_state(self, payload: dict[str, Any]) -> None:
        self.states.append(payload)

    async def pending_queue_count(self) -> int:
        return 3


class FakeMsg:
    def __init__(self, message: NATSMessage) -> None:
        self.subject = "puda.test-1.cmd.queue"
        self.data = message.model_dump_json().encode()

    async def ack(self) -> None:
        return None

    async def term(self) -> None:
        return None

    async def in_progress(self) -> None:
        return None


class CompleteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.processor = CommandProcessor(FakeClient())
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

    async def test_abort_stops_running_command_and_ends_run(self) -> None:
        async def stop(_m: NATSMessage) -> CommandResponse:
            self.release.set()
            return CommandResponse(status=CommandResponseStatus.SUCCESS,
                                   data={"driver_abort": True, "finished": True})

        response = await self.processor._immediate_complete(
            "run-1", _message("complete", params={"abort": True}), stop)
        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)
        self.assertEqual(response.data["aborted"]["name"], "move")
        self.assertTrue(response.data["driver_abort"])
        self.assertIsNone(self.processor.run_manager.get_active_run_id())
        await asyncio.wait_for(self.queued, 1)
        self.assertEqual(self.responses[-1].code, CommandResponseCode.COMMAND_CANCELLED)

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
