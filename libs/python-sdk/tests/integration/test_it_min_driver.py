"""A driver without lifecycle methods still pauses, resumes and resets."""
from __future__ import annotations

from nats_harness import EdgeTestCase, new_run


class MinimalDriverTests(EdgeTestCase):
    driver = "minimal"

    async def test_missing_lifecycle_hooks_succeed(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        self.assertEqual((await self.wire.call("pause", ""))["status"], "success")
        self.assertEqual((await self.wire.state())["state"], "paused")
        self.assertEqual((await self.wire.call("resume", ""))["status"], "success")
        self.assertEqual((await self.wire.call("reset", ""))["status"], "success")
        state = await self.wire.state()
        self.assertEqual((state["state"], state["run_id"]), ("idle", None))

    async def test_missing_estop_is_still_reported(self) -> None:
        self.assertEqual((await self.wire.call("estop", new_run()))["code"], "ESTOP_NOT_SUPPORTED")
