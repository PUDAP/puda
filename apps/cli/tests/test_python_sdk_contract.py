"""Opt-in real CLI/installed Python SDK contract smoke tests on a private broker.

Requires PUDA_TEST_CLI and PUDA_TEST_NATS_SERVER absolute binary paths and TMPDIR.
Run separately in each isolated SDK environment; never connects to a configured lab.
This is bounded smoke coverage, not a blanket support certification.
"""
import asyncio
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from importlib.metadata import version
from unittest.mock import patch

from puda.command import command, safety
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner
from puda.host_addresses import HostAddresses


class SoftwareDriver:
    """Software-only contract fixture; no device connections."""

    def __init__(self):
        self.calls = []

    @command
    @safety(summary="Software fixture confirmation", confirm=True)
    def echo(self, value: int, label: str = "default") -> dict:
        """Record the supplied value and label."""
        self.calls.append((value, label))
        return {"value": value, "label": label}

    @command
    def fail(self) -> None:
        """Exercise SDK error responses without hardware."""
        raise ValueError("intentional software fixture failure")


@unittest.skipUnless(
    os.getenv("PUDA_TEST_CLI") and os.getenv("PUDA_TEST_NATS_SERVER"),
    "set explicit test CLI and NATS server paths",
)
class PythonSDKContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="puda-contract-", dir=os.environ["TMPDIR"])
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.cli = str(Path(os.environ["PUDA_TEST_CLI"]).resolve())
        server = str(Path(os.environ["PUDA_TEST_NATS_SERVER"]).resolve())
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.server_log = (self.root / "nats.log").open("w+")
        self.addCleanup(self.server_log.close)
        self.server = subprocess.Popen(
            [server, "-a", "127.0.0.1", "-p", str(port), "-js", "-sd", str(self.root / "data")],
            stdout=self.server_log, stderr=subprocess.STDOUT,
        )
        self.addCleanup(self.stop_server)
        for _ in range(100):
            if self.server.poll() is not None:
                self.fail("private NATS server exited")
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.02)
        else:
            self.fail("private NATS server did not become ready")
        url = f"nats://127.0.0.1:{port}"
        cfgdir = self.root / "config" / "puda"
        cfgdir.mkdir(parents=True)
        (cfgdir / "config.json").write_text(json.dumps({
            "user": {"username": "contract-test", "user_id": "contract-test"},
            "active_profile": "isolated",
            "profiles": {"isolated": {"nats_servers": url, "e2e": False}},
        }))
        self.env = {"HOME": str(self.root), "XDG_CONFIG_HOME": str(cfgdir.parent),
                    "PUDA_NO_UPDATE_NOTIFIER": "1", "PATH": os.environ.get("PATH", "")}
        self.addresses = patch("puda.edge_nats_client.discover_host_addresses", return_value=HostAddresses())
        self.addresses.start()
        self.addCleanup(self.addresses.stop)
        self.client = EdgeNatsClient([url], "contract-edge")
        self.driver = SoftwareDriver()
        self.runner = EdgeRunner(self.client, self.driver, host_health=False)
        self.assertTrue(await asyncio.wait_for(self.client.connect(), 10))
        self.addAsyncCleanup(self.client.disconnect)
        await self.client.subscribe_ping()
        await self.client.subscribe_queue(self.runner._handle_execute)
        await self.client.subscribe_immediate(self.runner._handle_immediate)
        await self.runner._publish_commands()
        await self.client.publish_state({"state": "idle", "run_id": None})
        await self.client.nc.flush()

    def stop_server(self):
        self.server.terminate()
        try:
            self.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.server.kill()
            self.server.wait(timeout=5)

    async def cli_run(self, *args, input_text="", success=True):
        proc = await asyncio.create_subprocess_exec(
            self.cli, *args, cwd=self.root, env=self.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(input_text.encode()), 15)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        out, err = stdout.decode(), stderr.decode()
        if success:
            self.assertEqual(proc.returncode, 0, (args, out, err))
        else:
            self.assertNotEqual(proc.returncode, 0, (args, out, err))
        return out, err

    async def test_real_discovery_and_advisories(self):
        self.assertEqual(self.client.sdk_version, version("puda"))
        cli_output, _ = await self.cli_run("--version")
        cli_version = cli_output.splitlines()[0].removeprefix("v")
        self.assertRegex(cli_version, r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
        policy = json.loads((Path(__file__).resolve().parents[3] / "compatibility.json").read_text())
        # Independently evaluate the rule union; invalid metadata fails closed.
        def stable(value):
            if isinstance(value, str) and re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
                return tuple(map(int, value.split(".")))
            return None
        cli = stable(cli_version)
        sdk = stable(self.client.sdk_version)
        matching = []
        valid = True
        for rule in policy["compatibility"]:
            cr, sr = rule.get("cli", {}), rule.get("python_sdk", {})
            cmin, cmax = stable(cr.get("min")), stable(cr.get("max"))
            smin, smax = stable(sr.get("min")), stable(sr.get("max"))
            if cmin is None or cmax is None or smin is None or smax is None or cmin > cmax or smin > smax:
                valid = False
                break
            if cli is not None and cmin <= cli <= cmax:
                matching.append((smin, smax))
        for args in [("list",), ("info", "contract-edge")]:
            out, err = await self.cli_run("machine", *args, "--timeout", "100ms")
            payload = json.loads(out)
            if args[0] == "list":
                self.assertEqual(payload["count"], 1)
            else:
                self.assertEqual(payload["results"][0]["sdk_version"], version("puda"))
                self.assertEqual(payload["responded"], 1)
            # Check the declaration independently of the CLI's policy helper.
            # Passing this bounded smoke test is not comprehensive qualification.
            if not valid or not matching or sdk is None:
                self.assertIn("compatibility unknown", err)
            elif any(minimum <= sdk <= maximum for minimum, maximum in matching):
                self.assertNotIn("Python SDK", err)
            else:
                self.assertIn("outside the supported range", err)
                self.assertNotIn("compatibility unknown", err)
        for reported in ["", "unknown", "0.0.22.dev1", "not-a-version"]:
            self.client.sdk_version = reported
            out, err = await self.cli_run("machine", "info", "contract-edge", "--timeout", "100ms")
            self.assertEqual(json.loads(out)["responded"], 1)
            self.assertIn("compatibility unknown", err)
            self.assertNotIn("outside the supported range", err)
        out, err = await self.cli_run("machine", "info", "contract-edge,absent", "--timeout", "100ms", success=False)
        self.assertEqual(json.loads(out)["responded"], 1)
        self.assertEqual(json.loads(out)["failed"], 1)
        self.assertEqual(err.count("Python SDK compatibility unknown"), 1)
        out, err = await self.cli_run("machine", "info", "absent", "--timeout", "100ms", success=False)
        self.assertEqual(json.loads(out)["failed"], 1)
        self.assertNotIn("Python SDK", err)
        await self.client.disconnect()
        out, err = await self.cli_run("machine", "list", "--timeout", "100ms")
        self.assertEqual(json.loads(out), {"machines": [], "count": 0})
        self.assertNotIn("Python SDK", err)

    async def test_catalog_and_command_round_trip(self):
        out, _ = await self.cli_run("machine", "commands", "contract-edge")
        self.assertIn("echo(", json.loads(out)["commands"])
        out, _ = await self.cli_run("machine", "start", "contract-edge", "--run-id", "contract-run")
        self.assertEqual(json.loads(out)["failed"], 0)
        # Rejecting confirmation must not execute the software driver.
        await self.cli_run("machine", "run", "contract-edge", "echo", '{"value":7}', input_text="no\n", success=False)
        self.assertEqual(self.driver.calls, [])
        out, err = await self.cli_run("machine", "run", "contract-edge", "echo", '{"value":7}',
                                    "--kwargs", '{"label":"round-trip"}', "--yes", "--run-id", "contract-run")
        self.assertEqual(json.loads(out)["failed"], 0)
        self.assertEqual(self.driver.calls, [(7, "round-trip")])
        self.assertNotIn("Python SDK", err)  # execution is not gated by the map
        out, err = await self.cli_run("machine", "run", "contract-edge", "fail", "--run-id", "contract-run", success=False)
        self.assertEqual(json.loads(out)["failed"], 1)
        self.assertIn("intentional software fixture failure", out + err)
        out, _ = await self.cli_run("machine", "reset", "contract-edge")
        self.assertEqual(json.loads(out)["failed"], 0)


if __name__ == "__main__":
    unittest.main()
