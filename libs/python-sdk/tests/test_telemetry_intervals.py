import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from puda.command import command
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner


class Driver:
    @command
    def move(self):
        return None


class RunnerHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def _run_loop_once(self, runner):
        runner._ensure_connection = AsyncMock(return_value=True)
        real_sleep = asyncio.sleep

        async def stop_after_first_tick(delay, *args, **kwargs):
            if delay == 1:
                raise asyncio.CancelledError
            return await real_sleep(delay, *args, **kwargs)

        with patch("puda.edge_runner.asyncio.sleep", side_effect=stop_after_first_tick):
            with self.assertRaises(asyncio.CancelledError):
                await runner._run_main_loop()

    async def test_runner_publishes_heartbeat_without_telemetry_handler(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)
        await self._run_loop_once(EdgeRunner(client, Driver(), host_health=False))
        client._publish.assert_awaited_once_with(client.tlm_heartbeat, {})

    async def test_runner_publishes_heartbeat_before_telemetry_handler(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)
        handler = AsyncMock()
        await self._run_loop_once(EdgeRunner(client, Driver(), handler, host_health=False))
        client._publish.assert_awaited_once_with(client.tlm_heartbeat, {})
        handler.assert_awaited_once()

    async def test_runner_publishes_host_health_by_default(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)
        vitals = {"cpu": 1.0, "mem": 2.0, "temp": None}
        with patch("puda.edge_runner.read_host_health", return_value=vitals):
            await self._run_loop_once(EdgeRunner(client, Driver()))
        client._publish.assert_any_await(client.tlm_health, vitals)

    async def test_host_health_is_throttled(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)
        runner = EdgeRunner(client, Driver())
        with patch("puda.edge_runner.read_host_health", return_value={}), patch(
            "puda.edge_runner.time.monotonic", side_effect=[100.0, 104.9, 105.0]
        ):
            for _ in range(3):
                await runner._publish_host_health()
        self.assertEqual(client._publish.await_count, 2)

    async def test_host_health_can_be_disabled(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        client._publish = AsyncMock(return_value=True)
        await EdgeRunner(client, Driver(), host_health=False)._publish_host_health()
        client._publish.assert_not_awaited()


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
