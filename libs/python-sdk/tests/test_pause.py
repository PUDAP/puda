"""Pause holds the queue; resume runs held commands in order."""
from __future__ import annotations

import asyncio
import unittest
from typing import Any

from puda.command_processor import CommandProcessor
from puda.models import (
    CommandRequest,
    CommandResponse,
    CommandResponseStatus,
    MessageHeader,
    MessageType,
    NATSMessage,
)


def _message(name: str, run_id: str | None = "run-1") -> NATSMessage:
    return NATSMessage(
        header=MessageHeader(
            message_type=MessageType.COMMAND,
            user_id="user-1",
            username="user",
            machine_id="test-1",
            run_id=run_id,
        ),
        command=CommandRequest(name=name, step_number=1, machine_id="test-1"),
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
        self.response_queue = "puda.test-1.cmd.response.queue"
        self.response_immediate = "puda.test-1.cmd.response.immediate"

    async def publish_state(self, payload: dict[str, Any]) -> None:
        self.states.append(payload)


class FakeMsg:
    def __init__(self, message: NATSMessage) -> None:
        self.subject = "puda.test-1.cmd.queue"
        self.data = message.model_dump_json().encode()
        self.acked = False
        self.termed = False

    async def ack(self) -> None:
        self.acked = True

    async def term(self) -> None:
        self.termed = True

    async def in_progress(self) -> None:
        return None


async def _success(_message: NATSMessage) -> CommandResponse:
    return CommandResponse(status=CommandResponseStatus.SUCCESS)


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


if __name__ == "__main__":
    unittest.main()
