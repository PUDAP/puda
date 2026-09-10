"""Immediate reset clears run_id even when the driver has no reset command."""
from __future__ import annotations

import unittest
from typing import Any

from puda.command_processor import CommandProcessor
from puda.models import (
    CommandRequest,
    CommandResponse,
    CommandResponseCode,
    CommandResponseStatus,
    ImmediateCommand,
    MachineState,
    MessageHeader,
    MessageType,
    NATSMessage,
)


class FakeClient:
    def __init__(self) -> None:
        self.machine_id = "test-1"
        self.states: list[dict[str, Any]] = []

    async def publish_state(self, payload: dict[str, Any]) -> None:
        self.states.append(payload)


def _reset_message(run_id: str = "run-1") -> NATSMessage:
    return NATSMessage(
        header=MessageHeader(
            message_type=MessageType.COMMAND,
            user_id="user-1",
            username="user",
            machine_id="test-1",
            run_id=run_id,
        ),
        command=CommandRequest(
            name=ImmediateCommand.RESET,
            step_number=1,
            machine_id="test-1",
        ),
    )


class ImmediateResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_reset_command_still_clears_run_id(self) -> None:
        client = FakeClient()
        processor = CommandProcessor(client)
        await processor.run_manager.start_run("run-1")

        async def missing_reset(_message: NATSMessage) -> CommandResponse:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.UNKNOWN_COMMAND,
                message="Unknown or restricted command: reset",
            )

        response = await processor._immediate_reset(missing_reset, _reset_message())

        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)
        self.assertIsNone(processor.run_manager.get_active_run_id())
        self.assertEqual(client.states, [{"state": MachineState.IDLE, "run_id": None}])

    async def test_present_reset_command_is_invoked(self) -> None:
        client = FakeClient()
        processor = CommandProcessor(client)
        await processor.run_manager.start_run("run-1")
        called = False

        async def driver_reset(_message: NATSMessage) -> CommandResponse:
            nonlocal called
            called = True
            return CommandResponse(status=CommandResponseStatus.SUCCESS, data={"reset": True})

        response = await processor._immediate_reset(driver_reset, _reset_message())

        self.assertTrue(called)
        self.assertEqual(response.status, CommandResponseStatus.SUCCESS)
        self.assertEqual(response.data, {"reset": True})
        self.assertIsNone(processor.run_manager.get_active_run_id())
        self.assertEqual(client.states, [{"state": MachineState.IDLE, "run_id": None}])

    async def test_reset_execution_error_clears_run_id_and_fails(self) -> None:
        client = FakeClient()
        processor = CommandProcessor(client)
        await processor.run_manager.start_run("run-1")

        async def failing_reset(_message: NATSMessage) -> CommandResponse:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message="hardware fault",
            )

        response = await processor._immediate_reset(failing_reset, _reset_message())

        self.assertEqual(response.status, CommandResponseStatus.ERROR)
        self.assertEqual(response.code, CommandResponseCode.EXECUTION_ERROR)
        self.assertIsNone(processor.run_manager.get_active_run_id())
        self.assertEqual(client.states, [{"state": MachineState.ERROR, "run_id": None}])
