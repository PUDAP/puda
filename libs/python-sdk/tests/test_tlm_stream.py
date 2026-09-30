import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock

from puda import command, tlm_stream
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner
from puda.tlm_stream import iter_tlm_stream_methods


class Driver:
    def __init__(self):
        self.weight_calls = 0
        self.skip = False
        self.fail = False

    @command
    def move(self):
        return None

    @tlm_stream(interval=0.01)
    def weight(self):
        """Mass in grams.

        Not advertised.
        """
        self.weight_calls += 1
        if self.fail:
            raise RuntimeError("scale unplugged")
        if self.skip:
            return None
        return {"g": 1.5}

    @command
    @tlm_stream(interval=3.0, name="pos")
    def get_position(self):
        return {"x": 0.0}


async def telemetry():
    return None


def _client():
    client = EdgeNatsClient(["nats://localhost:4222"], "test-1")
    client._publish = AsyncMock(return_value=True)
    return client


class TlmStreamDecoratorTests(unittest.TestCase):
    def test_discovers_streams_with_name_override(self):
        streams = {name: spec for name, _, spec in iter_tlm_stream_methods(Driver())}
        self.assertEqual(set(streams), {"weight", "pos"})
        self.assertEqual(streams["weight"].interval, 0.01)
        self.assertEqual(streams["pos"].interval, 3.0)

    def test_rejects_non_positive_interval(self):
        for interval in (0, -1, True):
            with self.assertRaises(ValueError):
                tlm_stream(interval=interval)

    def test_rejects_invalid_names(self):
        for name in ("a b", "*", ">", "x.y", ""):
            with self.assertRaises(ValueError):
                tlm_stream(interval=1.0, name=name)

    def test_duplicate_names_raise(self):
        class Dup:
            @tlm_stream(interval=1.0, name="w")
            def a(self):
                return {}

            @tlm_stream(interval=1.0, name="w")
            def b(self):
                return {}

        with self.assertRaises(ValueError):
            iter_tlm_stream_methods(Dup())


class TlmStreamClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_unthrottled_stream_publishes_every_call(self):
        client = _client()
        client.declare_tlm_stream("ctrl", interval=0.02)
        for i in range(3):
            await client.publish_tlm_stream("ctrl", {"v": i})
        self.assertEqual(client._publish.await_count, 3)
        client._publish.assert_awaited_with("puda.test-1.tlm.stream.ctrl", {"v": 2})

    async def test_undeclared_stream_is_declared(self):
        client = _client()
        await client.publish_tlm_stream("weight", {"g": 1})
        self.assertIn("weight", client._tlm_streams)
        self.assertIsNone(client._tlm_streams["weight"].interval)

    async def test_declare_rejects_invalid_name(self):
        client = _client()
        with self.assertRaises(ValueError):
            client.declare_tlm_stream("a.b")

    async def test_position_uses_stream_subject(self):
        client = _client()
        await client.publish_position({"x": 1})
        client._publish.assert_awaited_with("puda.test-1.tlm.stream.pos", {"x": 1})
        self.assertEqual(client.tlm_pos, "puda.test-1.tlm.stream.pos")

    async def test_threadsafe_publish_from_worker_thread(self):
        client = _client()
        client._loop = asyncio.get_running_loop()
        futures = []
        thread = threading.Thread(
            target=lambda: futures.append(client.publish_tlm_stream_threadsafe("w", {"g": 2}))
        )
        thread.start()
        thread.join()
        self.assertTrue(await asyncio.wrap_future(futures[0]))
        client._publish.assert_awaited_with("puda.test-1.tlm.stream.w", {"g": 2})

    async def test_threadsafe_publish_without_loop_is_skipped(self):
        client = _client()
        self.assertIsNone(client.publish_tlm_stream_threadsafe("w", {"g": 2}))


class TlmStreamRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_declares_streams_with_docstring_description(self):
        client = _client()
        EdgeRunner(client, Driver(), telemetry)
        advertised = {s.name: s.advertised() for s in client._tlm_streams.values()}
        self.assertEqual(
            advertised["weight"],
            {
                "name": "weight",
                "subject": "puda.test-1.tlm.stream.weight",
                "interval": 0.01,
                "description": "Mass in grams.",
            },
        )
        self.assertIsNone(advertised["pos"]["description"])

    async def _run_streams(self, driver, seconds=0.06):
        client = _client()
        client.nc = MagicMock()
        runner = EdgeRunner(client, driver, telemetry)
        runner._start_tlm_streams()
        await asyncio.sleep(seconds)
        await runner._stop_tlm_streams()
        return client, runner

    async def test_polling_publishes_at_interval(self):
        driver = Driver()
        client, runner = await self._run_streams(driver)
        weight_publishes = [
            c for c in client._publish.await_args_list
            if c.args[0] == "puda.test-1.tlm.stream.weight"
        ]
        self.assertGreaterEqual(len(weight_publishes), 3)
        self.assertEqual(weight_publishes[0].args[1], {"g": 1.5})
        self.assertEqual(runner._tlm_stream_tasks, [])

    async def test_none_result_is_skipped(self):
        driver = Driver()
        driver.skip = True
        client, _ = await self._run_streams(driver)
        subjects = {c.args[0] for c in client._publish.await_args_list}
        self.assertNotIn("puda.test-1.tlm.stream.weight", subjects)
        self.assertGreater(driver.weight_calls, 1)

    async def test_errors_do_not_stop_the_stream(self):
        driver = Driver()
        driver.fail = True
        with self.assertLogs("puda.edge_runner", level="ERROR") as logs:
            await self._run_streams(driver)
        self.assertGreater(driver.weight_calls, 2)
        self.assertEqual(len(logs.records), 1)

    async def test_no_publish_while_disconnected(self):
        client = _client()
        runner = EdgeRunner(client, Driver(), telemetry)
        runner._start_tlm_streams()
        await asyncio.sleep(0.03)
        await runner._stop_tlm_streams()
        client._publish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
