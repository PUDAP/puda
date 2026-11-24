"""Commands sent while the edge is offline must not act when it returns."""
from __future__ import annotations

import asyncio

from nats_harness import EdgeTestCase, new_run


class OfflineBacklogTests(EdgeTestCase):
    edge_env = {"EDGE_IMMEDIATE_MAX_AGE": "2"}

    async def test_stale_immediates_are_discarded_on_restart(self) -> None:
        self.edge.stop()
        stale = new_run()
        await self.wire.immediate("start", stale)
        await self.wire.queue("echo", stale, 1, params={"message": "offline"})
        await asyncio.sleep(3)

        self.edge.start()
        await self.wire.wait_online()

        start = await self.wire.response("immediate", "start", stale)
        self.assertEqual(start["code"], "EXECUTION_ERROR")
        self.assertIn("Stale immediate command discarded", start["message"])
        queued = await self.wire.response("queue", "echo", stale, 1)
        self.assertEqual(queued["code"], "RUN_ID_MISMATCH")
        self.assertIsNone((await self.wire.state())["run_id"])
        self.assertNotIn("EXEC echo offline", self.edge_log())

        fresh = new_run()
        self.assertEqual((await self.wire.call("start", fresh))["status"], "success")

    async def test_fresh_immediate_is_processed(self) -> None:
        run = new_run()
        self.assertEqual((await self.wire.call("start", run))["status"], "success")
        self.assertEqual((await self.wire.state())["run_id"], run)
