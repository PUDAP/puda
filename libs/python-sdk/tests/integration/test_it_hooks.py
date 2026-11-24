"""Catalog advertises hooks separately; hooks cannot be queued."""
from __future__ import annotations

import json

from nats_harness import EdgeTestCase, new_run


class HookCatalogTests(EdgeTestCase):
    async def test_catalog_lists_hooks_separately(self) -> None:
        kv = await self.wire.js.key_value("MACHINE_COMMANDS")
        payload = json.loads((await kv.get(self.machine_id)).value)
        self.assertEqual(payload["hooks"], ["abort", "estop", "pause", "reset", "resume"])
        self.assertEqual(sorted(entry["name"] for entry in payload["catalog"]), ["echo", "fail", "hold"])

    async def test_queued_hook_is_rejected_and_ends_the_run(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        response = await self.wire.run("pause", run, 1)
        self.assertEqual(response["code"], "EXECUTION_ERROR")
        self.assertIn("use puda machine pause", response["message"])
        self.assertEqual((await self.wire.state())["state"], "idle")


class MinimalHookCatalogTests(EdgeTestCase):
    driver = "minimal"

    async def test_driver_without_hooks_reports_empty_list(self) -> None:
        kv = await self.wire.js.key_value("MACHINE_COMMANDS")
        self.assertEqual(json.loads((await kv.get(self.machine_id)).value)["hooks"], [])
