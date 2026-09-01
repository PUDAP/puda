import unittest

from puda.command import command
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner, machine_description


class Driver:
    @command
    def move(self):
        return None


class DescribedDriver:
    """Software-only test machine used to exercise PUDA without hardware.

    Extra paragraphs stay local to the driver and are not advertised.
    """

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

    async def test_runner_copies_driver_class_docstring_into_description(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        EdgeRunner(client, DescribedDriver(), telemetry)
        self.assertEqual(
            client.description,
            "Software-only test machine used to exercise PUDA without hardware.",
        )

    async def test_explicit_client_description_is_not_overwritten(self):
        client = EdgeNatsClient(
            ["nats://localhost:4222"],
            "test-1",
            description="Explicit override.",
        )
        EdgeRunner(client, DescribedDriver(), telemetry)
        self.assertEqual(client.description, "Explicit override.")

    async def test_missing_class_docstring_leaves_description_unset(self):
        client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
        EdgeRunner(client, Driver(), telemetry)
        self.assertIsNone(client.description)


class MachineDescriptionTests(unittest.TestCase):
    def test_first_paragraph_is_collapsed(self):
        self.assertEqual(
            machine_description(DescribedDriver()),
            "Software-only test machine used to exercise PUDA without hardware.",
        )

    def test_missing_docstring_returns_none(self):
        self.assertIsNone(machine_description(Driver()))


if __name__ == "__main__":
    unittest.main()
