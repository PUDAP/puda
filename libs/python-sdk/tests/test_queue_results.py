"""Queued results are stored before the ack; a redelivery never runs twice."""
from __future__ import annotations

import asyncio
import unittest

from processor_fakes import FakeClient, FakeJetStream, FakeMsg
from processor_fakes import message as _message

from puda import command_processor
from puda.command_processor import CommandProcessor
from puda.models import CommandResponse, CommandResponseStatus, NATSMessage


class QueueResultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.events: list[str] = []
        self.client = FakeClient()
        self.client.js = FakeJetStream(self.events)
        self.processor = CommandProcessor(self.client)
        await self.processor.run_manager.start_run("run-1")
        self.runs: list[str] = []

    async def handler(self, message: NATSMessage) -> CommandResponse:
        self.runs.append(message.command.name)
        return CommandResponse(status=CommandResponseStatus.SUCCESS, data={"ok": True})

    def msg(self, **kw) -> FakeMsg:
        return FakeMsg(_message("move"), events=self.events, **kw)

    async def test_result_is_stored_before_the_ack(self) -> None:
        await self.processor.process_queue(self.msg(seq=7), self.handler)
        self.assertEqual(self.events, ["publish", "ack"])
        self.assertEqual(self.client.js.published[0][2], {"Nats-Msg-Id": "test-1:7"})

    async def test_publish_is_retried_until_the_broker_takes_it(self) -> None:
        self.client.js.failures = 2
        delays = []
        real_sleep = asyncio.sleep

        async def fast_sleep(seconds: float) -> None:
            delays.append(seconds)
            await real_sleep(0)

        command_processor.asyncio.sleep = fast_sleep  # type: ignore[assignment]
        try:
            await self.processor.process_queue(self.msg(seq=7), self.handler)
        finally:
            command_processor.asyncio.sleep = real_sleep  # type: ignore[assignment]
        self.assertEqual(self.events, ["publish", "ack"])
        self.assertEqual([d for d in delays if d != command_processor.KEEP_ALIVE_INTERVAL][:2], [0.5, 1.0])

    async def test_redelivery_after_result_resends_it_and_does_not_run_again(self) -> None:
        await self.processor.process_queue(self.msg(seq=7), self.handler)
        again = self.msg(seq=7, delivered=2)
        await self.processor.process_queue(again, self.handler)
        self.assertEqual(self.runs, ["move"])
        self.assertTrue(again.acked)
        first, second = self.client.js.published
        self.assertEqual((first[1], first[2]), (second[1], second[2]))  # same body and Nats-Msg-Id

    async def test_redelivery_without_result_is_answered_unknown_and_not_run(self) -> None:
        redelivered = self.msg(seq=9, delivered=2)
        await self.processor.process_queue(redelivered, self.handler)
        self.assertEqual(self.runs, [])
        self.assertTrue(redelivered.termed)
        (response,) = self.client.js.responses()
        self.assertEqual(response["code"], "EXECUTION_ERROR")
        self.assertIn("Outcome unknown", response["message"])
        self.assertIsNone(self.processor.run_manager.get_active_run_id())

    async def test_command_nacked_on_pause_runs_when_redelivered(self) -> None:
        await self.processor._immediate_pause(_message("pause"), self.handler)
        await self.processor.process_queue(self.msg(seq=11), self.handler)
        self.runs.clear()
        await self.processor._immediate_resume(self.handler, _message("resume"))
        self.runs.clear()
        await self.processor.process_queue(self.msg(seq=11, delivered=2), self.handler)
        self.assertEqual(self.runs, ["move"])


if __name__ == "__main__":
    unittest.main()
