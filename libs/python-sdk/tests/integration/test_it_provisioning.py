"""The edge creates missing JetStream objects but never modifies existing ones (D-7)."""
from __future__ import annotations

import asyncio
import json
import unittest
import uuid

import nats
from nats.js.api import StreamConfig

from nats_harness import KV_BUCKETS, STREAMS_DIR, Broker, Edge, EdgeTestCase, Wire, new_run


class UnprovisionedBrokerTests(EdgeTestCase):
    provisioned = False

    async def test_edge_creates_missing_streams_and_buckets(self) -> None:
        run = new_run()
        await self.wire.call("start", run)
        self.assertEqual((await self.wire.run("echo", run, 1))["status"], "success")
        names = {info.config.name for info in await self.wire.js.streams_info()}
        self.assertTrue({"COMMAND_QUEUE", "RESPONSE_QUEUE", "RESPONSE_IMMEDIATE",
                         "KV_MACHINE_STATE", "KV_MACHINE_COMMANDS"} <= names)
        self.assertNotIn("COMMAND_IMMEDIATE", names)
        self.assertIn("is missing; creating", self.edge_log())


class ProvisionedStreamsAreNotModifiedTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_streams_keep_their_config(self) -> None:
        broker = Broker()
        broker.start()
        self.addCleanup(broker.cleanup)
        nc = await nats.connect(broker.url)
        self.addAsyncCleanup(nc.close)
        js = nc.jetstream()
        for path in sorted(STREAMS_DIR.glob("*.json")):
            config = json.loads(path.read_text())
            if config["name"] == "RESPONSE_QUEUE":
                config["retention"] = "limits"  # deliberately wrong
            await js.add_stream(StreamConfig.from_response(config))
        for bucket in KV_BUCKETS:
            await js.create_key_value(bucket=bucket, history=1)
        before = {i.config.name: i.config.as_dict() for i in await js.streams_info()}

        machine = f"it-{uuid.uuid4().hex[:8]}"
        wire = Wire(broker, machine)
        await wire.connect()
        self.addAsyncCleanup(wire.close)
        edge = Edge(broker, machine)
        edge.start()
        self.addCleanup(edge.stop)
        await wire.wait_online()
        await asyncio.sleep(0.5)

        after = {i.config.name: i.config.as_dict() for i in await js.streams_info()}
        self.assertEqual(after, before)
        self.assertEqual(after["COMMAND_QUEUE"]["max_msgs_per_subject"], 100)
        self.assertIn("Stream RESPONSE_QUEUE does not match the protocol", edge.output())
