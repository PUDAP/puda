"""Pause holds the queue on a real broker; resume runs the backlog in order."""
from __future__ import annotations

import asyncio

from nats_harness import EdgeTestCase, new_run


class PauseTests(EdgeTestCase):
    async def test_pause_holds_and_resume_runs_backlog_in_order(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        self.assertEqual((await self.wire.call("pause", ""))["status"], "success")

        for step, message in enumerate(["first", "second", "third"], start=1):
            await self.wire.queue("echo", run, step, params={"message": message})
        await asyncio.sleep(1.5)
        self.assertEqual(self.wire.matching("queue", "echo", run, 1), [])
        self.assertNotIn("EXEC echo", self.edge_log())

        self.assertEqual((await self.wire.call("resume", ""))["status"], "success")
        for step in (1, 2, 3):
            self.assertEqual((await self.wire.response("queue", "echo", run, step))["status"], "success")
        log = self.edge_log()
        self.assertLess(log.index("EXEC echo first"), log.index("EXEC echo second"))
        self.assertLess(log.index("EXEC echo second"), log.index("EXEC echo third"))

        await asyncio.sleep(0.5)
        for step in (1, 2, 3):
            self.assertEqual(len(self.wire.matching("queue", "echo", run, step)), 1)

    async def test_pause_lets_running_command_finish(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.queue("hold", run, 1, params={"seconds": 1.5})
        await self.wait_for_log("EXEC hold")
        await self.wire.call("pause", "")
        await self.wire.queue("echo", run, 2, params={"message": "held"})

        self.assertEqual((await self.wire.response("queue", "hold", run, 1))["status"], "success")
        await asyncio.sleep(1.0)
        self.assertEqual(self.wire.matching("queue", "echo", run, 2), [])

        await self.wire.call("resume", "")
        self.assertEqual((await self.wire.response("queue", "echo", run, 2))["status"], "success")

    async def test_estop_discards_paused_backlog(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.call("pause", "")
        await self.wire.queue("echo", run, 1, params={"message": "never"})
        await asyncio.sleep(0.5)

        await self.wire.call("estop", run)
        self.assertEqual((await self.wire.response("queue", "echo", run, 1))["code"], "MACHINE_ESTOPPED")
        self.assertNotIn("EXEC echo never", self.edge_log())
