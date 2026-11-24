"""Malformed commands are answered when they can be correlated (D-6)."""
from __future__ import annotations

import asyncio
import json

from nats_harness import EdgeTestCase, new_run


class MalformedTests(EdgeTestCase):
    def _bad_envelope(self, run: str | None, step: int) -> bytes:
        envelope = self.wire.envelope("echo", run, step)
        envelope["header"]["message_type"] = "bogus"
        return json.dumps(envelope).encode()

    async def test_correlatable_malformed_queue_command_is_answered(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.publish_raw("queue", self._bad_envelope(run, 1))
        response = await self.wire.response("queue", "echo", run, 1)
        self.assertEqual(response["code"], "EXECUTION_ERROR")
        self.assertIn("Invalid command envelope: header.message_type", response["message"])
        # The run survives and the queue keeps going.
        ok = await self.wire.run("echo", run, 2, params={"message": "next"})
        self.assertEqual(ok["status"], "success")

    async def test_correlatable_malformed_immediate_is_answered_without_error_state(self) -> None:
        await self.wire.publish_raw("immediate", self._bad_envelope("", 0))
        response = await self.wire.response("immediate", "echo", "", 0)
        self.assertEqual(response["code"], "EXECUTION_ERROR")
        self.assertEqual((await self.wire.state())["state"], "idle")

    async def test_uncorrelatable_payloads_are_handled(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.publish_raw("queue", b"{not json")
        reply = await self.wire.request_raw(b"[1, 2]")
        self.assertEqual(reply["response"]["code"], "EXECUTION_ERROR")
        self.assertNotIn("header", reply)
        await asyncio.sleep(1)
        # Neither shows up on the response streams: no client could match them.
        self.assertEqual([r for r in self.wire.responses if r["command"]["name"] != "start"], [])
        self.assertEqual((await self.wire.state())["state"], "idle")
        self.assertEqual((await self.wire.run("echo", run, 1))["status"], "success")
