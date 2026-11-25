"""Immediate commands are request/reply: an offline edge gets nothing stale."""
from __future__ import annotations

import asyncio
import json

from nats.errors import NoRespondersError

from puda import CommandService
from puda.models import CommandRequest

from nats_harness import EdgeTestCase, new_run


class OfflineTests(EdgeTestCase):
    async def test_immediate_to_offline_edge_fails_fast_and_never_replays(self) -> None:
        self.edge.stop()
        stale = new_run()
        with self.assertRaises(NoRespondersError):
            await self.wire.call("start", stale, timeout=2)
        await self.wire.queue("echo", stale, 1, params={"message": "offline"})

        self.edge.start()
        await self.wire.wait_online()

        # The start never reached the edge, so the queued command has no run.
        queued = await self.wire.response("queue", "echo", stale, 1)
        self.assertEqual(queued["code"], "RUN_ID_MISMATCH")
        self.assertIsNone((await self.wire.state())["run_id"])
        self.assertNotIn("EXEC echo offline", self.edge_log())
        self.assertEqual((await self.wire.call("start", new_run()))["status"], "success")

    async def test_python_client_reports_offline_without_waiting(self) -> None:
        self.edge.stop()
        service = CommandService(servers=[self.broker.url])
        await service.connect()
        try:
            request = CommandRequest(name="start", step_number=0, machine_id=self.machine_id)
            started = asyncio.get_running_loop().time()
            reply = await service.send_immediate_command(
                request=request, run_id=new_run(), user_id="it", username="it", timeout=5
            )
            elapsed = asyncio.get_running_loop().time() - started
        finally:
            await service.disconnect()
            self.edge.start()
            await self.wire.wait_online()
        self.assertIsNone(reply)
        self.assertLess(elapsed, 2)

    async def test_reply_is_also_recorded_on_the_response_stream(self) -> None:
        run = new_run()
        reply = await self.wire.call("start", run)
        self.assertEqual(reply["status"], "success")
        self.assertEqual((await self.wire.response("immediate", "start", run))["status"], "success")

    async def test_start_is_idempotent_for_the_active_run(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        again = await self.wire.call("start", run)
        self.assertEqual((again["status"], again["data"]), ("success", {"already_started": True}))
        self.assertEqual((await self.wire.call("start", new_run()))["code"], "RUN_ID_MISMATCH")

    async def test_unparseable_request_still_gets_a_reply(self) -> None:
        reply = await self.wire.request_raw(b"{not json")
        self.assertEqual(reply["response"]["code"], "EXECUTION_ERROR")
        self.assertEqual((await self.wire.state())["state"], "idle")
        await asyncio.sleep(0)
        self.assertIsInstance(json.dumps(reply), str)

