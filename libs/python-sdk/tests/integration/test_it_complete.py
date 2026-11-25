"""complete / complete --abort against a real broker."""
from __future__ import annotations

import asyncio
import time

from nats_harness import EdgeTestCase, new_run


class CompleteTests(EdgeTestCase):
    async def test_complete_refused_while_running_then_abort(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.queue("hold", run, 1, params={"seconds": 30})
        await self.wire.queue("echo", run, 2, params={"message": "behind"})
        await self.wait_for_log("EXEC hold")

        refused = await self.wire.call("complete", run)
        self.assertEqual(refused["code"], "EXECUTION_LOCKED")
        self.assertEqual(refused["data"]["running"]["name"], "hold")
        self.assertEqual(refused["data"]["queued"], 1)

        aborted = await self.wire.call("complete", run, step=1, params={"abort": True})
        self.assertEqual(aborted["status"], "success")
        self.assertEqual(aborted["data"]["aborted"]["name"], "hold")
        self.assertTrue(aborted["data"]["driver_abort"])
        self.assertNotIn("finished", aborted["data"])
        self.assertEqual(aborted["data"]["queued"], 1)
        self.assertEqual((await self.wire.response("queue", "hold", run, 1))["code"], "COMMAND_CANCELLED")
        self.assertEqual((await self.wire.response("queue", "echo", run, 2))["code"], "RUN_ID_MISMATCH")
        self.assertIn("EXEC abort", self.edge_log())
        state = await self.wire.state()
        self.assertEqual((state["state"], state["run_id"]), ("idle", None))

        again = await self.wire.call("complete", run, step=2)
        self.assertEqual(again["data"], {"already_completed": True})

    async def test_cancel_is_unknown_command(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        self.assertEqual((await self.wire.call("cancel", run))["code"], "UNKNOWN_COMMAND")
        self.assertEqual((await self.wire.state())["run_id"], run)


class AbortWithoutDriverAbortTests(EdgeTestCase):
    driver = "minimal"

    async def test_abort_returns_at_once_and_answers_the_command_when_it_returns(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.queue("hold", run, 1, params={"seconds": 3})
        await asyncio.sleep(0.5)
        started = time.monotonic()
        aborted = await self.wire.call("complete", run, params={"abort": True})
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(aborted["status"], "success")
        self.assertFalse(aborted["data"]["driver_abort"])
        # The run is over but the driver call is not: busy with no run.
        state = await self.wire.state()
        self.assertEqual((state["state"], state["run_id"]), ("busy", None))
        self.assertEqual(self.wire.matching("queue", "hold", run, 1), [])
        self.assertEqual((await self.wire.response("queue", "hold", run, 1))["code"], "COMMAND_CANCELLED")
        self.assertLess(started + 2.0, time.monotonic())
        state = await self.wire.state()
        self.assertEqual((state["state"], state["run_id"]), ("idle", None))
