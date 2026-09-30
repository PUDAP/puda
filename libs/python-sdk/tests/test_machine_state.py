import unittest

from puda import command, machine_state
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner
from puda.host_health import read_host_health


class StatefulDriver:
    def __init__(self):
        self.homed = True

    @command
    def move(self):
        return None

    @machine_state
    def snapshot(self):
        return {"homed": self.homed}


class PlainDriver:
    @command
    def move(self):
        return None


class TwoStates(PlainDriver):
    @machine_state
    def a(self):
        return {}

    @machine_state
    def b(self):
        return {}


def _client():
    return EdgeNatsClient(["nats://localhost:4222"], "test-1")


class MachineStateTests(unittest.TestCase):
    def test_runner_uses_machine_state_method(self):
        client = _client()
        driver = StatefulDriver()
        EdgeRunner(client, driver)
        driver.homed = False
        self.assertEqual(client.state_handler(), {"homed": False})

    def test_explicit_state_handler_overrides_decorator(self):
        client = _client()
        EdgeRunner(client, StatefulDriver(), state_handler=lambda: {"x": 1})
        self.assertEqual(client.state_handler(), {"x": 1})

    def test_no_machine_state_leaves_handler_unset(self):
        client = _client()
        EdgeRunner(client, PlainDriver())
        self.assertIsNone(client.state_handler)

    def test_multiple_machine_state_methods_raise(self):
        with self.assertRaises(ValueError):
            EdgeRunner(_client(), TwoStates())


class HostHealthTests(unittest.TestCase):
    def test_read_host_health_shape(self):
        vitals = read_host_health()
        self.assertEqual(set(vitals), {"cpu", "mem", "temp"})
        self.assertIsInstance(vitals["mem"], float)


if __name__ == "__main__":
    unittest.main()
