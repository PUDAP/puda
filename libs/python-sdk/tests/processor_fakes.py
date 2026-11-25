"""Shared fakes for CommandProcessor unit tests (no broker)."""
from __future__ import annotations

import json
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
            protocol_version="1.0",
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

    def seal(self, _subject: str, data: bytes) -> bytes:
        return data


class FakeJetStream:
    """Records JetStream publishes (response streams)."""

    def __init__(self, events: list[str] | None = None, failures: int = 0) -> None:
        self.published: list[tuple[str, bytes, dict | None]] = []
        self.events = events if events is not None else []
        self.failures = failures  # the first N publishes raise (broker unreachable)

    async def publish(self, subject: str, payload: bytes, headers: dict | None = None, **_kw) -> None:
        if self.failures:
            self.failures -= 1
            raise ConnectionError("no broker")
        self.published.append((subject, payload, headers))
        self.events.append("publish")

    def responses(self, kind: str = "queue") -> list[dict]:
        """Response payloads published to cmd.response.<kind>, decoded."""
        return [json.loads(p)["response"] for s, p, _ in self.published if s.endswith(f".cmd.response.{kind}")]


class FakeClient:
    """Stands in for EdgeNatsClient: records state and JetStream publishes."""

    def __init__(self, *, queued: int | None = None) -> None:
        self.machine_id = MACHINE_ID
        self.states: list[dict[str, Any]] = []
        self.encryption = PlainEncryption()
        self.js = FakeJetStream()
        self.response_queue = f"puda.{MACHINE_ID}.cmd.response.queue"
        self.response_immediate = f"puda.{MACHINE_ID}.cmd.response.immediate"
        if queued is not None:
            async def pending_queue_count() -> int:
                return queued
            self.pending_queue_count = pending_queue_count

    async def publish_state(self, payload: dict[str, Any]) -> None:
        self.states.append(payload)


class FakeMsg:
    """A delivered JetStream message.

    *seq* and *delivered* set the stream sequence and delivery count; *events*
    collects "ack"/"term" in order, shared with a FakeJetStream to check that
    results are stored before the ack.
    """

    def __init__(self, msg: NATSMessage, kind: str = "queue", seq: int | None = None,
                 delivered: int = 1, events: list[str] | None = None) -> None:
        self.subject = f"puda.{MACHINE_ID}.cmd.{kind}"
        self.data = msg.model_dump_json().encode()
        self.acked = False
        self.termed = False
        self.nakked = False
        self.events = events if events is not None else []
        if seq is not None:
            self.metadata = SimpleNamespace(sequence=SimpleNamespace(stream=seq), num_delivered=delivered)

    async def ack(self) -> None:
        self.acked = True
        self.events.append("ack")

    async def term(self) -> None:
        self.termed = True
        self.events.append("term")

    async def nak(self, delay: float | None = None) -> None:
        self.nakked = True

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
