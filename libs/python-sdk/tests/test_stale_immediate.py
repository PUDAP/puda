"""Immediate commands stored too long ago (edge was offline) are discarded."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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


class PlainEncryption:
    def open_payload(self, _subject: str, data: bytes) -> bytes:
        return data


class FakeClient:
    def __init__(self, max_age: float | None = 10.0) -> None:
        self.machine_id = "test-1"
        self.states: list[dict[str, Any]] = []
        self.encryption = PlainEncryption()
        self.js = None
        self.immediate_max_age = max_age
        self.response_immediate = "puda.test-1.cmd.response.immediate"

    async def publish_state(self, payload: dict[str, Any]) -> None:
        self.states.append(payload)


class FakeMsg:
    def __init__(self, name: str, age: float | None) -> None:
        message = NATSMessage(
            header=MessageHeader(message_type=MessageType.COMMAND, user_id="u", username="u",
                                 machine_id="test-1", run_id="run-1"),
            command=CommandRequest(name=name, step_number=0, machine_id="test-1"),
        )
        self.subject = "puda.test-1.cmd.immediate"
        self.data = message.model_dump_json().encode()
        self.acked = False
        if age is not None:
            self.metadata = SimpleNamespace(timestamp=datetime.now(timezone.utc) - timedelta(seconds=age))

    async def ack(self) -> None:
        self.acked = True


async def _success(_m: NATSMessage) -> CommandResponse:
    return CommandResponse(status=CommandResponseStatus.SUCCESS)


class StaleImmediateTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_start_is_acked_and_ignored(self) -> None:
        processor = CommandProcessor(FakeClient())
        msg = FakeMsg("start", age=60)
        await processor.process_immediate(msg, _success)
        self.assertTrue(msg.acked)
        self.assertIsNone(processor.run_manager.get_active_run_id())

    async def test_stale_estop_does_not_latch(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor.process_immediate(FakeMsg("estop", age=60), _success)
        self.assertFalse(processor.is_estopped)

    async def test_fresh_start_runs(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor.process_immediate(FakeMsg("start", age=1), _success)
        self.assertEqual(processor.run_manager.get_active_run_id(), "run-1")

    async def test_unknown_age_and_disabled_check_run(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor.process_immediate(FakeMsg("start", age=None), _success)
        self.assertEqual(processor.run_manager.get_active_run_id(), "run-1")

        disabled = CommandProcessor(FakeClient(max_age=None))
        await disabled.process_immediate(FakeMsg("start", age=3600), _success)
        self.assertEqual(disabled.run_manager.get_active_run_id(), "run-1")


if __name__ == "__main__":
    unittest.main()
