"""Bugs found in review of the 0.1.0 edge (reproduced before the fixes)."""
from __future__ import annotations

import asyncio
import time

from nats_harness import EdgeTestCase, new_run


class ReconnectSerialTests(EdgeTestCase):
    async def test_queue_stays_serial_after_reconnect(self) -> None:
        """One pull loop after a reconnect: commands never overlap."""
        run = new_run()
        await self.wire.call("start", run)
        for _ in range(2):
            self.broker.restart()
            await self.wire.wait_online(timeout=20)
        await self.wire.call("start", run)  # already_started; the run survived
        self.assertEqual(self.edge_log().count("Started background task for pulling queue messages"), 1)
        await self.wire.queue("hold", run, 1, params={"seconds": 2})
        await self.wire.queue("echo", run, 2, params={"message": "second"})
        first = await self.wire.response("queue", "hold", run, 1, timeout=15)
        second = await self.wire.response("queue", "echo", run, 2, timeout=15)
        self.assertEqual((first["status"], second["status"]), ("success", "success"), (first, second))

    async def test_pause_holds_after_reconnect(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        self.broker.restart()
        await self.wire.wait_online(timeout=20)
        await self.wire.call("pause")
        await self.wire.queue("echo", run, 1, params={"message": "while-paused"})
        await asyncio.sleep(3)
        self.assertNotIn("EXEC echo while-paused", self.edge_log())
        await self.wire.call("resume")
        self.assertEqual((await self.wire.response("queue", "echo", run, 1))["status"], "success")


class AbortTests(EdgeTestCase):
    async def test_estop_is_not_delayed_by_complete_abort(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.queue("stuck", run, 1, params={"seconds": 8})
        await self.wait_for_log("EXEC stuck")
        abort = asyncio.create_task(self.wire.call("complete", run, params={"abort": True}, timeout=20))
        await asyncio.sleep(0.3)
        started = time.monotonic()
        estop = await self.wire.call("estop", timeout=20)
        elapsed = time.monotonic() - started
        await abort
        self.assertEqual(estop["status"], "success")
        self.assertLess(elapsed, 1.0, f"estop took {elapsed:.1f}s")
        await self.wire.call("reset")

    async def test_next_command_waits_for_the_aborted_driver_call(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.queue("stuck", run, 1, params={"seconds": 6})
        await self.wait_for_log("EXEC stuck")
        await self.wire.call("complete", run, params={"abort": True}, timeout=20)
        run2 = new_run()
        await self.wire.call("start", run2)
        await self.wire.queue("echo", run2, 1, params={"message": "next"})
        await self.wire.response("queue", "echo", run2, 1, timeout=20)
        log = self.edge_log()
        self.assertLess(log.index("DONE stuck"), log.index("EXEC echo next"), "next command overlapped the hung call")
