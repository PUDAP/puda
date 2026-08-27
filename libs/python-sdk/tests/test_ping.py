import json
import unittest
from unittest.mock import AsyncMock, patch

from puda.edge_nats_client import EdgeNatsClient


class FakeSubscription:
    def __init__(self):
        self.unsubscribe = AsyncMock()


class FakeNATS:
    def __init__(self):
        self.callbacks = {}
        self.subscriptions = {}
        self.flush = AsyncMock()

    async def subscribe(self, subject, cb):
        subscription = FakeSubscription()
        self.callbacks[subject] = cb
        self.subscriptions[subject] = subscription
        return subscription


class FakeMessage:
    def __init__(self, data=b"ping"):
        self.data = data
        self.respond = AsyncMock()


class PingTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_and_broadcast_ping_return_structured_pong(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client.nc = FakeNATS()
        client._started_at = 100.0
        client.sdk_version = "9.8.7"

        await client.subscribe_ping()
        self.assertEqual(
            set(client.nc.callbacks),
            {"puda.test-1.cmd.ping", "puda.cmd.ping"},
        )
        client.nc.flush.assert_awaited_once()

        for subject in ("puda.test-1.cmd.ping", "puda.cmd.ping"):
            msg = FakeMessage()
            with patch("puda.edge_nats_client.time.monotonic", return_value=112.5):
                await client.nc.callbacks[subject](msg)

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
        await client.nc.callbacks[client.ping](msg)

        payload = json.loads(msg.respond.await_args.args[0])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["message"], "expected ping")

    async def test_resubscribe_replaces_previous_subscriptions(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        first_nc = FakeNATS()
        client.nc = first_nc
        await client.subscribe_ping()

        second_nc = FakeNATS()
        client.nc = second_nc
        await client.subscribe_ping()

        first_nc.subscriptions[client.ping].unsubscribe.assert_awaited_once()
        first_nc.subscriptions[client.ping_broadcast].unsubscribe.assert_awaited_once()
        self.assertIs(client._ping_sub, second_nc.subscriptions[client.ping])
        self.assertIs(
            client._ping_broadcast_sub,
            second_nc.subscriptions[client.ping_broadcast],
        )


if __name__ == "__main__":
    unittest.main()
