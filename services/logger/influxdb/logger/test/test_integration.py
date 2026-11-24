"""Opt-in Docker tests; use only isolated containers and temporary test keys."""

import asyncio
import base64
import gzip
import json
import os
import socket
import ssl
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import nats
import pytest
from nats.js.api import AckPolicy, ConsumerConfig, RetentionPolicy, StreamConfig
from puda import e2e

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DOCKER_TESTS") != "1", reason="set RUN_DOCKER_TESTS=1"
)


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.STDOUT
    ).strip()


async def eventually(predicate, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.2)
    raise AssertionError("Timed out waiting for integration condition")


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "e2ee"])
async def test_container_pipeline(tmp_path, encrypted):
    image = os.getenv("LOGGER_TEST_IMAGE", "puda-influxdb-e2ee-test:local")
    suffix = uuid.uuid4().hex[:10]
    broker, logger = f"puda-test-nats-{suffix}", f"puda-test-logger-{suffix}"
    containers = []
    received = []
    failures = []
    accepting = threading.Event()
    accepting.set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get("Transfer-Encoding") == "chunked":
                chunks = []
                while True:
                    size = int(self.rfile.readline().split(b";", 1)[0], 16)
                    if not size:
                        self.rfile.readline()
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.read(2)
                body = b"".join(chunks)
            else:
                body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            if accepting.is_set():
                received.append(body.decode())
                self.send_response(204)
            else:
                failures.append(body.decode())
                self.send_response(503)
            self.end_headers()

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    nc = None
    try:
        broker_args = []
        tls_args = []
        logger_args = []
        compose_env = os.environ.copy()
        compose_env["PUDA_NATS_CA"] = ""
        compose_env["PUDA_E2E_KEY_FILE"] = ""
        key_path = tmp_path / "keys" / "e2e.key"
        original_key = b"a" * 32
        if encrypted:
            certs = tmp_path / "certs"
            certs.mkdir()
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(certs / "server.key"),
                    "-out",
                    str(certs / "ca.pem"),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=DNS:localhost,IP:127.0.0.1",
                ],
                check=True,
                capture_output=True,
            )
            (certs / "server.key").chmod(0o644)  # Disposable test certificate only.
            key_path.parent.mkdir()
            key_path.write_text(
                "encrypt=" + base64.b64encode(original_key).decode() + "\n"
            )
            broker_args = ["-v", f"{certs}:/certs:ro"]
            tls_args = [
                "--tls",
                "--tlscert",
                "/certs/ca.pem",
                "--tlskey",
                "/certs/server.key",
            ]
            compose_env["PUDA_NATS_CA"] = str(certs / "ca.pem")
            compose_env["PUDA_E2E_KEY_FILE"] = str(key_path)
        # Exercise the real Compose host-path mappings without loading a user's .env.
        rendered = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    ".env.example",
                    "-f",
                    "compose.yml",
                    "config",
                    "--no-env-resolution",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=compose_env,
                text=True,
            )
        )["services"]["influxdb-logger"]
        for name in ("PUDA_NATS_CA", "PUDA_E2E_KEY_FILE"):
            value = rendered["environment"][name]
            assert bool(value) == encrypted
            logger_args += ["-e", f"{name}={value}"]
        for mount in rendered["volumes"]:
            if mount["target"].startswith("/run/puda-"):
                assert mount["bind"]["create_host_path"] is False
                spec = f"type=bind,source={mount['source']},target={mount['target']}"
                if mount.get("read_only"):
                    spec += ",readonly"
                logger_args += ["--mount", spec]
        # Pin the selected host port: Docker reassigns anonymous ports on restart.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            broker_port = sock.getsockname()[1]
        docker(
            "run",
            "-d",
            "--name",
            broker,
            "-p",
            f"127.0.0.1:{broker_port}:4222",
            *broker_args,
            "nats:2.14.5",
            "-js",
            "-sd",
            "/data",
            *tls_args,
        )
        containers.append(broker)
        port = docker("port", broker, "4222/tcp").rsplit(":", 1)[1]
        server = f"{'tls' if encrypted else 'nats'}://127.0.0.1:{port}"
        options = (
            {"tls": ssl.create_default_context(cafile=str(certs / "ca.pem"))}
            if encrypted
            else {}
        )
        nc = await nats.connect(server, **options)
        js = nc.jetstream()
        # Simulate pre-existing upstream streams/durables with custom delivery subjects.
        for suffix in ("queue", "immediate"):
            stream = "RESPONSE_" + suffix.upper()
            durable = "puda_logger_cmd_responses_" + suffix
            await js.add_stream(
                config=StreamConfig(
                    name=stream,
                    subjects=[f"puda.*.cmd.response.{suffix}"],
                    retention=RetentionPolicy.LIMITS,
                    max_age=86400,
                    max_msgs=10000,
                )
            )
            await js.add_consumer(
                stream,
                config=ConsumerConfig(
                    durable_name=durable,
                    deliver_subject=f"_INBOX.upstream.{suffix}",
                    deliver_group=durable,
                    filter_subject=f"puda.*.cmd.response.{suffix}",
                    ack_policy=AckPolicy.EXPLICIT,
                    max_ack_pending=20000,
                ),
            )
        # Shorter aggregation windows keep this test fast; other production settings remain.
        template = (
            Path(__file__).resolve().parents[1] / "telegraf.conf.template"
        ).read_text()
        test_config = tmp_path / "telegraf.conf.template"
        test_config.write_text(
            template.replace('period = "60s"', 'period = "2s"').replace(
                'delay = "5s"', 'delay = "1s"'
            )
        )
        logger_args += ["-v", f"{test_config}:/etc/telegraf/telegraf.conf.template:ro"]
        docker(
            "run",
            "-d",
            "--name",
            logger,
            "--network",
            "host",
            "-e",
            f"NATS_SERVERS={server}",
            "-e",
            f"INFLUXDB_URL=http://127.0.0.1:{http.server_port}",
            "-e",
            "INFLUXDB_TOKEN=test-token",
            *logger_args,
            image,
        )
        containers.append(logger)
        await eventually(lambda: "Subscriber ready" in docker("logs", logger))
        docker("exec", logger, "/healthcheck.sh")
        for suffix in ("queue", "immediate"):
            info = await js.consumer_info(
                "RESPONSE_" + suffix.upper(), "puda_logger_cmd_responses_" + suffix
            )
            assert info.config.deliver_subject == f"_INBOX.upstream.{suffix}"
            assert info.config.max_ack_pending == 20000
            assert (
                await js.stream_info("RESPONSE_" + suffix.upper())
            ).config.max_msgs == 10000
        e2e.set_ring(e2e.Ring(encrypt=original_key) if encrypted else None)

        async def publish(name):
            header = {
                "machine_id": "test-machine",
                "timestamp": "2026-07-07T09:41:42Z",
                "username": "ACME\\test user",
                "run_id": "run-1",
            }
            command = {"name": name, "step_number": 1, "version": "1.0"}
            data = {
                "header": header,
                "command": command,
                "response": {"status": "success", "message": 'ok "quoted"'},
            }
            for topic in (
                "cmd.queue",
                "cmd.immediate",
                "cmd.response.queue",
                "cmd.response.immediate",
            ):
                subject = "puda.test-machine." + topic
                payload = e2e.seal(subject, json.dumps(data).encode())
                if "response" in topic:
                    await js.publish(subject, payload)
                else:
                    await nc.publish(subject, payload)
            subject = "puda.test-machine.tlm.health"
            await nc.publish(
                subject,
                e2e.seal(
                    subject,
                    json.dumps(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "cpu": 6.0,
                            "connected": True,
                            "sample": name,
                        }
                    ).encode(),
                ),
            )
            for stream, sample in (
                (
                    "pos",
                    {"x": 1, "y": 2.5, "ready": True, "sample": name,
                     "value": {"axes": [1, 2], "missing": None}},
                ),
                (
                    "weight",
                    {"mass_g": 12.5, "unit": "g", "sample": name,
                     "value": 'quoted "text"\nnext\\line µ'},
                ),
            ):
                subject = "puda.test-machine.tlm.stream." + stream
                await nc.publish(subject, e2e.seal(subject, json.dumps(sample).encode()))
            await nc.flush()

        await publish("initial")
        await eventually(
            lambda: len([line for body in received for line in body.splitlines()]) >= 7
        )
        lines = [line for body in received for line in body.splitlines()]
        assert sum("cmd_name=initial" in line for line in lines) == 4
        assert any(line.startswith("telemetry,") and "cpu=6" in line for line in lines)
        assert all("connected=" not in line and "connected_mean=" not in line for line in lines)
        streams = [line for line in lines if line.startswith("telemetry_stream,")]
        assert len(streams) == 2
        samples = {}
        for line in streams:
            tags, fields = line.split(" ", 1)
            field_text = fields.rsplit(" ", 1)[0]
            assert field_text.startswith("data=")
            sample = json.loads(json.loads(field_text.removeprefix("data=")))
            stream = next(
                tag.removeprefix("stream=") for tag in tags.split(",")
                if tag.startswith("stream=")
            )
            samples[stream] = sample
            assert sample["sample"] == "initial"
            assert "_mean" not in line
        assert samples["pos"]["x"] == 1
        assert samples["pos"]["ready"] is True
        assert samples["pos"]["value"] == {"axes": [1, 2], "missing": None}
        assert samples["weight"]["mass_g"] == 12.5
        assert samples["weight"]["value"] == 'quoted "text"\nnext\\line µ'
        assert all("subject=" not in line.split(" ", 1)[0] for line in lines)
        command_lines = [line for line in lines if line.startswith("commands,")]
        assert all("run_id=run-1" in line for line in command_lines)
        assert all("username=ACME\\\\test\\ user" in line for line in command_lines)
        assert all('run_id="' not in line and 'username="' not in line for line in command_lines)
        assert not any(
            "Error in plugin" in line for line in docker("logs", logger).splitlines()
        )

        # Invalid JSON and, in E2EE mode, plaintext must not become metrics.
        await nc.publish(
            "puda.test-machine.cmd.queue",
            e2e.seal("puda.test-machine.cmd.queue", b"not-json"),
        )
        await nc.flush()
        await eventually(lambda: "Invalid message" in docker("logs", logger))
        if encrypted:
            await nc.publish("puda.test-machine.cmd.queue", b'{"secret":"do-not-log"}')
            await nc.flush()
            await eventually(lambda: "Cannot decrypt" in docker("logs", logger))
            assert "do-not-log" not in docker("logs", logger)

            # Rotate using the real SDK frame and KV AAD, then verify persistence.
            kv = await js.create_key_value(bucket=e2e.KEYRING_BUCKET)
            next_key = b"b" * 32
            record = {
                "new_key": base64.b64encode(next_key).decode(),
                "old_key": base64.b64encode(original_key).decode(),
                "encrypt_kid": e2e.kid_hex(e2e.kid_for(next_key)),
            }
            sealed = e2e.seal(
                e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY),
                json.dumps(record).encode(),
            )
            await kv.put(e2e.KEYRING_KEY, sealed)
            await eventually(
                lambda: base64.b64encode(next_key).decode() in key_path.read_text()
            )
            e2e.set_ring(e2e.Ring(encrypt=next_key, previous=original_key))
            await publish("rotated")
            await eventually(
                lambda: any("cmd_name=rotated" in body for body in received)
            )
            await kv.delete(e2e.KEYRING_KEY)
            await eventually(lambda: "previous=" not in key_path.read_text())

        # Telegraf buffers while the Influx HTTP endpoint fails and retries afterwards.
        accepting.clear()
        await publish("outage")
        await eventually(lambda: any("cmd_name=outage" in body for body in failures))
        accepting.set()
        await eventually(lambda: any("cmd_name=outage" in body for body in received))

        docker("restart", broker)
        await eventually(lambda: "NATS reconnected" in docker("logs", logger))
        await eventually(lambda: nc.is_connected)
        await publish("reconnected")
        await eventually(
            lambda: any("cmd_name=reconnected" in body for body in received)
        )

        # Kill only this test container's subscriber; execd must start it again.
        docker(
            "exec",
            logger,
            "/opt/puda/bin/python",
            "-c",
            "import os,pathlib,signal; "
            "pids=[p for p in pathlib.Path('/proc').iterdir() if p.name.isdigit()]; "
            "[(os.kill(int(p.name),signal.SIGKILL)) for p in pids "
            "if int(p.name)!=os.getpid() and "
            "b'/opt/puda/subscriber.py' in (p/'cmdline').read_bytes().split(b'\\0')]",
        )
        await publish("offline")
        await eventually(lambda: docker("logs", logger).count("Subscriber ready") >= 2)
        await eventually(
            lambda: (
                sum(
                    "cmd_name=offline" in line
                    for body in received
                    for line in body.splitlines()
                )
                >= 2
            )
        )
        offline = [
            line
            for body in received
            for line in body.splitlines()
            if "cmd_name=offline" in line
        ]
        assert len(offline) == 2
        assert all("msg_type=response" in line for line in offline)
        docker("exec", logger, "/healthcheck.sh")
        await publish("restarted")
        await eventually(lambda: any("cmd_name=restarted" in body for body in received))
    finally:
        if nc is not None:
            await nc.close()
        for name in reversed(containers):
            logs = docker("logs", name)
            print(f"\n{name}:\n{logs}")
            docker("rm", "-f", name)
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)
        e2e.reset()
