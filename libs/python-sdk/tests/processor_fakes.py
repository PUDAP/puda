"""Shared fakes for CommandProcessor unit tests (no broker)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from puda.models import (
    CommandRequest,
    CommandResponse,
    CommandResponseCode,
    CommandResponseStatus,
    MessageHeader,
    MessageType,
    NATSMessage,
)

MACHINE_ID = "test-1"


def message(name: str, run_id: str | None = "run-1", params: dict | None = None,
            step_number: int = 1) -> NATSMessage:
    return NATSMessage(
        header=MessageHeader(
            message_type=MessageType.COMMAND,
            user_id="user-1",
            username="user",
            machine_id=MACHINE_ID,
            run_id=run_id,
        ),
        command=CommandRequest(name=name, step_number=step_number, machine_id=MACHINE_ID,
                               params=params or {}),
    )


class PlainEncryption:
    def open_payload(self, _subject: str, data: bytes) -> bytes:
        return data


class FakeClient:
    """Stands in for EdgeNatsClient: records state, no JetStream."""

    def __init__(self, *, immediate_max_age: float | None = 10.0, queued: int | None = None) -> None:
        self.machine_id = MACHINE_ID
        self.states: list[dict[str, Any]] = []
        self.encryption = PlainEncryption()
        self.js = None
        self.immediate_max_age = immediate_max_age
        self.response_queue = f"puda.{MACHINE_ID}.cmd.response.queue"
        self.response_immediate = f"puda.{MACHINE_ID}.cmd.response.immediate"
        if queued is not None:
            async def pending_queue_count() -> int:
                return queued
            self.pending_queue_count = pending_queue_count

    async def publish_state(self, payload: dict[str, Any]) -> None:
        self.states.append(payload)


class FakeMsg:
    """A delivered JetStream message; *age* sets the stored timestamp."""

    def __init__(self, msg: NATSMessage, kind: str = "queue", age: float | None = None) -> None:
        self.subject = f"puda.{MACHINE_ID}.cmd.{kind}"
        self.data = msg.model_dump_json().encode()
        self.acked = False
        self.termed = False
        if age is not None:
            self.metadata = SimpleNamespace(timestamp=datetime.now(timezone.utc) - timedelta(seconds=age))

    async def ack(self) -> None:
        self.acked = True

    async def term(self) -> None:
        self.termed = True

    async def in_progress(self) -> None:
        return None


async def success(_message: NATSMessage) -> CommandResponse:
    return CommandResponse(status=CommandResponseStatus.SUCCESS)


async def failure(_message: NATSMessage) -> CommandResponse:
    return CommandResponse(
        status=CommandResponseStatus.ERROR,
        code=CommandResponseCode.EXECUTION_ERROR,
        message="driver failed",
    )
