"""A full per-machine queue refuses new commands and never deletes queued ones."""
from __future__ import annotations

import asyncio
import json

from nats.js.errors import APIError

from nats_harness import STREAMS_DIR, EdgeTestCase, new_run

from puda.edge_nats_client import COMMAND_QUEUE_PER_MACHINE, _STREAM_DEFAULTS


class QueueCapTests(EdgeTestCase):
    async def test_eleventh_command_is_refused_and_none_is_deleted(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        await self.wire.call("pause")  # the edge stops pulling; commands wait in the stream
        for step in range(1, COMMAND_QUEUE_PER_MACHINE + 1):
            await self.wire.queue("echo", run, step, params={"message": f"m{step}"})
        with self.assertRaises(APIError) as refused:
            await self.wire.queue("echo", run, COMMAND_QUEUE_PER_MACHINE + 1, params={"message": "extra"})
        self.assertEqual(refused.exception.err_code, 10077)
        await self.wire.call("resume")
        for step in range(1, COMMAND_QUEUE_PER_MACHINE + 1):
            response = await self.wire.response("queue", "echo", run, step, timeout=20)
            self.assertEqual(response["status"], "success", response)
        await asyncio.sleep(0.5)
        log = self.edge_log()
        self.assertEqual([f"EXEC echo m{s}" in log for s in range(1, COMMAND_QUEUE_PER_MACHINE + 1)],
                         [True] * COMMAND_QUEUE_PER_MACHINE)
        self.assertNotIn("EXEC echo extra", log)

    def test_edge_defaults_match_the_provisioned_configs(self) -> None:
        for name, defaults in _STREAM_DEFAULTS.items():
            provisioned = json.loads((STREAMS_DIR / f"{name}.json").read_text())
            self.assertEqual({k: provisioned.get(k) for k in defaults}, defaults, name)
