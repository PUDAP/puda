"""Baseline wire behaviour against a real broker (no protocol changes)."""
from __future__ import annotations

from nats_harness import EdgeTestCase, new_run


class BaselineTests(EdgeTestCase):
    async def test_run_lifecycle(self) -> None:
        run = new_run()
        self.assertEqual((await self.wire.call("start", run))["status"], "success")
        self.assertEqual((await self.wire.state())["run_id"], run)

        response = await self.wire.run("echo", run, 1, params={"message": "hi"})
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["data"], {"message": "hi"})

        self.assertEqual((await self.wire.call("complete", run))["status"], "success")
        state = await self.wire.state()
        self.assertEqual((state["state"], state["run_id"]), ("idle", None))

    async def test_queued_command_without_run_is_rejected(self) -> None:
        response = await self.wire.run("echo", new_run(), 1)
        self.assertEqual(response["code"], "RUN_ID_MISMATCH")

    async def test_estop_latches_until_reset(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.queue("hold", run, 1, params={"seconds": 10})
        await self.wait_for_log("EXEC hold")

        self.assertEqual((await self.wire.call("estop", run))["status"], "success")
        self.assertEqual((await self.wire.response("queue", "hold", run, 1))["code"], "COMMAND_CANCELLED")
        self.assertEqual((await self.wire.state())["state"], "estopped")
        self.assertEqual((await self.wire.call("start", new_run()))["code"], "MACHINE_ESTOPPED")

        self.assertEqual((await self.wire.call("reset", ""))["status"], "success")
        self.assertEqual((await self.wire.state())["state"], "idle")

    async def test_single_pong(self) -> None:
        self.assertEqual(await self.wire.pong_count(), 1)
