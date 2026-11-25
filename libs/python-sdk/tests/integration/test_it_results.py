"""A queued result is stored before the ack; a redelivery never runs twice."""
from __future__ import annotations

import asyncio
import json

import nats
from nats.js.api import ConsumerConfig

from nats_harness import EdgeTestCase, new_run


class ResultDurabilityTests(EdgeTestCase):
    async def _results_reader(self):
        """A durable consumer on RESPONSE_QUEUE: survives broker restarts, unlike core taps."""
        nc = await nats.connect(self.broker.url, max_reconnect_attempts=-1, reconnect_time_wait=0.2)
        js = nc.jetstream()
        subject = f"puda.{self.machine_id}.cmd.response.queue"
        durable = f"it_results_{self.machine_id}"
        sub = await js.pull_subscribe(subject, durable=durable, stream="RESPONSE_QUEUE",
                                      config=ConsumerConfig(durable_name=durable, filter_subject=subject,
                                                            ack_policy="explicit"))
        return nc, sub

    async def _read(self, sub, timeout: float = 30) -> list[dict]:
        out = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                for msg in await sub.fetch(10, timeout=1):
                    out.append(json.loads(msg.data))
                    await msg.ack()
            except Exception:
                pass
            if out:
                return out
        return out

    async def test_result_survives_a_broker_outage_at_completion(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        nc, sub = await self._results_reader()
        try:
            await self.wire.queue("hold", run, 1, params={"seconds": 2})
            await self.wait_for_log("EXEC hold")
            self.broker.stop()  # the command finishes while the broker is down
            await asyncio.sleep(4)
            self.broker.start()
            results = await self._read(sub)
        finally:
            await nc.close()
        self.assertEqual([(r["command"]["name"], r["response"]["status"]) for r in results], [("hold", "success")])
        self.assertEqual(self.edge_log().count("EXEC hold"), 1)

    async def test_command_redelivered_after_a_crash_is_not_run_again(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        nc, sub = await self._results_reader()
        try:
            await self.wire.queue("hold", run, 1, params={"seconds": 60})
            await self.wait_for_log("EXEC hold")
            self.edge.kill()
            self.edge.start()
            await self.wire.wait_online()
            # JetStream redelivers after ack_wait (30 s).
            results = await self._read(sub, timeout=45)
        finally:
            await nc.close()
        self.assertEqual(len(results), 1, results)
        response = results[0]["response"]
        self.assertEqual(response["code"], "EXECUTION_ERROR")
        self.assertIn("Outcome unknown", response["message"])
        self.assertEqual(self.edge_log().count("EXEC hold"), 1)
