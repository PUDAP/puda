import unittest

from puda.command import command
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner


class Driver:
    @command
    def move(self):
        return None


async def telemetry():
    return None


class EdgeRunnerPingStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_wires_execution_status_into_ping(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        runner = EdgeRunner(client, Driver(), telemetry)

        self.assertEqual(client.runtime_status_handler(), "idle")
        self.assertTrue(await runner.exec_state.acquire_lock("run-1"))
        try:
            self.assertEqual(client.runtime_status_handler(), "busy")
        finally:
            runner.exec_state.release_lock()


if __name__ == "__main__":
    unittest.main()
