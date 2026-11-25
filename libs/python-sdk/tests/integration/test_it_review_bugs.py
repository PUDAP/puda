"""Bugs found in review of the 0.1.0 edge (reproduced before the fixes)."""
from __future__ import annotations

import asyncio
import time

from nats_harness import EdgeTestCase, new_run


class AbortTests(EdgeTestCase):
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
