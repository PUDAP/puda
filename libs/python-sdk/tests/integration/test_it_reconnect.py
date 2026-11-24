"""After a broker restart the edge keeps one connection (D-4)."""
from __future__ import annotations

import asyncio
import time

from nats_harness import EdgeTestCase, new_run


class ReconnectTests(EdgeTestCase):
    async def test_broker_restart_keeps_one_connection_and_republishes(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        self.assertEqual(self.broker.connection_count(), 2)

        self.broker.restart()
        await self.wire.wait_online(timeout=20)
        deadline = time.monotonic() + 10
        while self.broker.connection_count() != 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        await asyncio.sleep(1)  # a duplicate connect() would show up in this window

        self.assertEqual(self.broker.connection_count(), 2)  # wire + edge
        self.assertEqual(await self.wire.pong_count(), 1)
        state = await self.wire.state()
        self.assertEqual((state["state"], state["run_id"]), ("idle", run))
        self.assertEqual((await self.wire.run("echo", run, 1, params={"message": "after"}))["status"], "success")
