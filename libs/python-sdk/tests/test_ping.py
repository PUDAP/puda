import json
import unittest
from unittest.mock import AsyncMock, patch

from puda.edge_nats_client import EdgeNatsClient


class FakeSubscription:
    def __init__(self):
        self.unsubscribe = AsyncMock()


class FakeNATS:
    def __init__(self):
        self.subject = None
        self.callback = None
        self.subscription = FakeSubscription()

    async def subscribe(self, subject, cb):
        self.subject = subject
        self.callback = cb
        return self.subscription


class FakeMessage:
    def __init__(self, data=b"ping"):
        self.data = data
        self.respond = AsyncMock()


class PingTests(unittest.IsolatedAsyncioTestCase):
    async def test_ping_subscription_returns_structured_pong(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client.nc = FakeNATS()
        client._started_at = 100.0
        client.sdk_version = "9.8.7"

        await client.subscribe_ping()
        self.assertEqual(client.nc.subject, "puda.test-1.cmd.ping")

        msg = FakeMessage()
        with patch("puda.edge_nats_client.time.monotonic", return_value=112.5):
            await client.nc.callback(msg)

        msg.respond.assert_awaited_once()
        payload = json.loads(msg.respond.await_args.args[0])
        self.assertEqual(payload["status"], "pong")
        self.assertEqual(payload["machine_id"], "test-1")
        self.assertEqual(payload["sdk_version"], "9.8.7")
        self.assertEqual(payload["uptime_seconds"], 12.5)
        self.assertIn("timestamp", payload)

    async def test_non_ping_payload_returns_error_response(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client.nc = FakeNATS()
        await client.subscribe_ping()

        msg = FakeMessage(b"not-ping")
        await client.nc.callback(msg)

        payload = json.loads(msg.respond.await_args.args[0])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["message"], "expected ping")

    async def test_resubscribe_replaces_previous_subscription(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        first_nc = FakeNATS()
        client.nc = first_nc
        await client.subscribe_ping()

        second_nc = FakeNATS()
        client.nc = second_nc
        await client.subscribe_ping()

        first_nc.subscription.unsubscribe.assert_awaited_once()
        self.assertIs(client._ping_sub, second_nc.subscription)


if __name__ == "__main__":
    unittest.main()
