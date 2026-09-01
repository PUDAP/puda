import unittest
from unittest.mock import AsyncMock, patch

from puda.edge_nats_client import EdgeNatsClient


class HeartbeatIntervalTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_publishes_immediately_then_every_five_seconds(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)

        with patch("puda.edge_nats_client.time.monotonic", side_effect=[100.0, 101.0, 104.999, 105.0]):
            await client.publish_heartbeat()
            await client.publish_heartbeat()
            await client.publish_heartbeat()
            await client.publish_heartbeat()

        self.assertEqual(client._publish.await_count, 2)
        client._publish.assert_awaited_with(client.tlm_heartbeat, {})

    async def test_connection_reset_allows_immediate_heartbeat(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)

        with patch("puda.edge_nats_client.time.monotonic", side_effect=[100.0, 101.0]):
            await client.publish_heartbeat()
            client._reset_connection_state()
            await client.publish_heartbeat()

        self.assertEqual(client._publish.await_count, 2)


class PositionIntervalTests(unittest.IsolatedAsyncioTestCase):
    async def test_position_publishes_immediately_then_every_three_seconds(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)

        with patch("puda.edge_nats_client.time.monotonic", side_effect=[200.0, 201.0, 202.999, 203.0]):
            await client.publish_position({"x": 0, "y": 0, "z": 0})
            await client.publish_position({"x": 1, "y": 1, "z": 1})
            await client.publish_position({"x": 2, "y": 2, "z": 2})
            await client.publish_position({"x": 3, "y": 3, "z": 3})

        self.assertEqual(client._publish.await_count, 2)
        client._publish.assert_awaited_with(
            client.tlm_pos, {"x": 3, "y": 3, "z": 3}
        )

    async def test_connection_reset_allows_immediate_position(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)

        with patch("puda.edge_nats_client.time.monotonic", side_effect=[200.0, 201.0]):
            await client.publish_position({"x": 0, "y": 0, "z": 0})
            client._reset_connection_state()
            await client.publish_position({"x": 1, "y": 1, "z": 1})

        self.assertEqual(client._publish.await_count, 2)


if __name__ == "__main__":
    unittest.main()
