"""Observe the actual serialized/encrypted boundary, not _publish mocks."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from puda.edge_nats_client import EdgeNatsClient


class TelemetryEnvelopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_and_stream_wrap_measurements_once(self):
        client = EdgeNatsClient(["nats://127.0.0.1:14222"], "test-1")
        client.nc = AsyncMock()
        values = {"timestamp": "sensor timestamp", "data": {"x": [1, None]}, "status": None}
        original = json.loads(json.dumps(values))
        with patch.object(client, "_format_timestamp", return_value="2026-07-07T09:41:42Z"):
            await client.publish_health(values)
            self.assertTrue(await client.publish_tlm_stream("position", values))
        for call in client.nc.publish.await_args_list:
            plain = client.encryption.open_payload(call.kwargs["subject"], call.kwargs["payload"])
            self.assertEqual(json.loads(plain), {"timestamp": "2026-07-07T09:41:42Z", "data": original})
        self.assertEqual(values, original)
        self.assertEqual([c.kwargs["subject"] for c in client.nc.publish.await_args_list],
                         ["puda.test-1.tlm.health", "puda.test-1.tlm.stream.position"])

    async def test_shared_publish_remains_flat_for_non_telemetry(self):
        client = EdgeNatsClient(["nats://127.0.0.1:14222"], "test-1")
        client.nc = AsyncMock()
        await client.publish_heartbeat()
        call = client.nc.publish.await_args
        payload = json.loads(client.encryption.open_payload(call.kwargs["subject"], call.kwargs["payload"]))
        self.assertEqual(set(payload), {"timestamp"})
