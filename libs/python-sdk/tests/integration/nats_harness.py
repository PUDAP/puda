"""Throwaway NATS broker + edge subprocess + raw wire client for integration tests.

Tests using this module are skipped unless a ``nats-server`` binary is found via
``PUDA_NATS_SERVER`` or ``PATH``. Streams and KV buckets are provisioned from
``infra/nats/jetstream/streams/*.json`` the same way ``setup_streams.sh`` does,
so the edge runs against production-shaped JetStream objects.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nats
from nats.js.api import StreamConfig

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
STREAMS_DIR = REPO / "infra" / "nats" / "jetstream" / "streams"
KV_BUCKETS = ("MACHINE_STATE", "MACHINE_COMMANDS", "LIVESTREAMS", "E2E_KEYRING", "E2E_KEYFILES")
EDGE_SCRIPT = HERE / "edge_driver.py"


def nats_server_binary() -> str | None:
    return os.environ.get("PUDA_NATS_SERVER") or shutil.which("nats-server")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Broker:
    """A private JetStream-enabled nats-server on a free loopback port."""

    def __init__(self) -> None:
        binary = nats_server_binary()
        if binary is None:
            raise unittest.SkipTest("nats-server not found (set PUDA_NATS_SERVER)")
        self.binary = binary
        self.port = _free_port()
        self.http_port = _free_port()
        self.dir = Path(tempfile.mkdtemp(prefix="puda-it-"))
        self.url = f"nats://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        conf = self.dir / "nats.conf"
        conf.write_text(
            f'listen: 127.0.0.1:{self.port}\nhttp: 127.0.0.1:{self.http_port}\n'
            f'jetstream {{ store_dir: "{self.dir / "js"}", max_mem: 64M, max_file: 256M }}\n'
        )
        self.conf = conf

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [self.binary, "-c", str(self.conf)],
            stdout=subprocess.DEVNULL,
            stderr=open(self.dir / "server.log", "ab"),
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("nats-server did not start")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            self.proc.wait(10)
            self.proc = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def connection_count(self) -> int:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{self.http_port}/connz") as resp:
            return int(json.load(resp)["num_connections"])

    async def provision(self) -> None:
        nc = await nats.connect(self.url)
        js = nc.jetstream()
        for path in sorted(STREAMS_DIR.glob("*.json")):
            await js.add_stream(StreamConfig.from_response(json.loads(path.read_text())))
        for bucket in KV_BUCKETS:
            await js.create_key_value(bucket=bucket, history=1)
        await nc.close()


class Edge:
    """``edge_driver.py`` running as a subprocess against the broker."""

    def __init__(self, broker: Broker, machine_id: str, driver: str = "full",
                 env: dict[str, str] | None = None) -> None:
        self.broker = broker
        self.env = env or {}
        self.machine_id = machine_id
        self.driver = driver
        self.log = broker.dir / f"edge-{machine_id}.log"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(EDGE_SCRIPT), self.broker.url, self.machine_id, self.driver],
            stdout=open(self.log, "ab"),
            stderr=subprocess.STDOUT,
            env={**os.environ, **self.env},
        )

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.send_signal(signal.SIGINT)
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
        self.proc = None

    def kill(self) -> None:
        """SIGKILL: the edge dies without any cleanup, as on a crash or power loss."""
        if self.proc is None:
            return
        self.proc.kill()
        self.proc.wait(5)
        self.proc = None

    def output(self) -> str:
        return self.log.read_text(errors="replace") if self.log.exists() else ""


class Wire:
    """Raw client: publishes envelopes and records every response for one machine."""

    def __init__(self, broker: Broker, machine_id: str) -> None:
        self.broker = broker
        self.machine_id = machine_id
        self.nc: Any = None
        self.js: Any = None
        self.responses: list[dict[str, Any]] = []

    async def connect(self) -> None:
        self.nc = await nats.connect(self.broker.url, max_reconnect_attempts=-1, reconnect_time_wait=0.2)
        self.js = self.nc.jetstream()

        async def record(msg) -> None:
            try:
                body = json.loads(msg.data)
            except ValueError:
                return
            body["_subject"] = msg.subject
            self.responses.append(body)

        await self.nc.subscribe(f"puda.{self.machine_id}.cmd.response.>", cb=record)
        await self.nc.flush()

    async def close(self) -> None:
        if self.nc is not None:
            await self.nc.close()

    def envelope(self, name: str, run_id: str | None, step: int, params=None, kwargs=None,
                 timestamp: str | None = None) -> dict[str, Any]:
        command: dict[str, Any] = {"name": name, "params": params or {}, "step_number": step,
                                   "machine_id": self.machine_id}
        if kwargs is not None:
            command["kwargs"] = kwargs
        return {"header": {"protocol_version": "1.0", "message_type": "command", "user_id": "it", "username": "it",
                           "machine_id": self.machine_id, "run_id": run_id,
                           "timestamp": timestamp or _now()},
                "command": command}

    async def publish_raw(self, kind: str, data: bytes) -> None:
        """Queue commands go through JetStream; immediate ones are core NATS."""
        if kind == "queue":
            await self.js.publish(f"puda.{self.machine_id}.cmd.queue", data)
        else:
            await self.nc.publish(f"puda.{self.machine_id}.cmd.{kind}", data, reply=self.nc.new_inbox())

    async def queue(self, name: str, run_id: str | None, step: int, **kw) -> None:
        await self.publish_raw("queue", json.dumps(self.envelope(name, run_id, step, **kw)).encode())

    async def immediate(self, name: str, run_id: str | None = None, step: int = 0, **kw) -> None:
        """Fire an immediate command without waiting for the reply."""
        body = json.dumps(self.envelope(name, run_id, step, **kw)).encode()
        await self.nc.publish(f"puda.{self.machine_id}.cmd.immediate", body, reply=self.nc.new_inbox())

    async def request_raw(self, data: bytes, timeout: float = 10) -> dict[str, Any]:
        """Send raw bytes as an immediate request and return the parsed reply."""
        reply = await self.nc.request(f"puda.{self.machine_id}.cmd.immediate", data, timeout=timeout)
        return json.loads(reply.data)

    def matching(self, kind: str, name: str, run_id: str | None, step: int) -> list[dict[str, Any]]:
        return [
            r for r in self.responses
            if r["_subject"].endswith(f"cmd.response.{kind}")
            and r["command"]["name"] == name
            and r["header"].get("run_id") == run_id
            and r["command"]["step_number"] == step
        ]

    async def response(self, kind: str, name: str, run_id: str | None, step: int = 0,
                       timeout: float = 10) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.matching(kind, name, run_id, step)
            if found:
                return found[0]["response"]
            await asyncio.sleep(0.05)
        raise AssertionError(f"no {kind} response for {name} run={run_id} step={step}")

    async def call(self, name: str, run_id: str | None = None, step: int = 0, timeout: float = 10,
                   **kw) -> dict[str, Any]:
        """Immediate command as core request/reply; returns the reply's response."""
        body = json.dumps(self.envelope(name, run_id, step, **kw)).encode()
        return (await self.request_raw(body, timeout))["response"]

    async def run(self, name: str, run_id: str, step: int, timeout: float = 15, **kw) -> dict[str, Any]:
        await self.queue(name, run_id, step, **kw)
        return await self.response("queue", name, run_id, step, timeout)

    async def state(self) -> dict[str, Any]:
        kv = await self.js.key_value("MACHINE_STATE")
        entry = await kv.get(self.machine_id)
        return json.loads(entry.value)

    async def pong_count(self, window: float = 1.0) -> int:
        inbox = self.nc.new_inbox()
        replies: list[bytes] = []

        async def collect(msg) -> None:
            replies.append(msg.data)

        sub = await self.nc.subscribe(inbox, cb=collect)
        await self.nc.publish(f"puda.{self.machine_id}.cmd.ping", b"ping", reply=inbox)
        await asyncio.sleep(window)
        await sub.unsubscribe()
        return sum(1 for r in replies if b'"pong"' in r)

    async def wait_online(self, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                reply = await self.nc.request(f"puda.{self.machine_id}.cmd.ping", b"ping", timeout=0.5)
                if b'"pong"' in reply.data:
                    await asyncio.sleep(0.3)  # let state/catalog puts land
                    return
            except Exception:
                await asyncio.sleep(0.2)
        raise AssertionError(f"edge {self.machine_id} did not come online")


def new_run() -> str:
    return str(uuid.uuid4())


class EdgeTestCase(unittest.IsolatedAsyncioTestCase):
    """One broker per test class; one fresh machine and edge per test."""

    driver = "full"
    edge_env: dict[str, str] = {}
    provisioned = True
    broker: Broker

    @classmethod
    def setUpClass(cls) -> None:
        cls.broker = Broker()
        cls.broker.start()
        if cls.provisioned:
            asyncio.run(cls.broker.provision())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.broker.cleanup()

    async def asyncSetUp(self) -> None:
        self.machine_id = f"it-{uuid.uuid4().hex[:8]}"
        self.wire = Wire(self.broker, self.machine_id)
        await self.wire.connect()
        self.edge = Edge(self.broker, self.machine_id, self.driver, self.edge_env)
        self.edge.start()
        await self.wire.wait_online()

    async def asyncTearDown(self) -> None:
        self.edge.stop()
        await self.wire.close()

    def edge_log(self) -> str:
        return self.edge.output()

    async def wait_for_log(self, text: str, timeout: float = 10, count: int = 1) -> None:
        deadline = time.monotonic() + timeout
        while self.edge_log().count(text) < count:
            if time.monotonic() > deadline:
                raise AssertionError(f"{text!r} x{count} not in edge log")
            await asyncio.sleep(0.05)
