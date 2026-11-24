"""PUDA NATS input for Telegraf. stdout is exclusively Influx line protocol."""

import asyncio
import calendar
import json
import logging
import math
import os
import re
import signal
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import nats
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    RetentionPolicy,
    StreamConfig,
)
from nats.js.errors import NotFoundError
from puda import e2e

log = logging.getLogger("subscriber")
RESPONSE_STREAMS = {
    "RESPONSE_QUEUE": "puda.*.cmd.response.queue",
    "RESPONSE_IMMEDIATE": "puda.*.cmd.response.immediate",
}
RESPONSE_CONSUMERS = {
    "RESPONSE_QUEUE": "puda_logger_cmd_responses_queue",
    "RESPONSE_IMMEDIATE": "puda_logger_cmd_responses_immediate",
}


def duration_seconds(value):
    parts = re.findall(r"(\d+(?:\.\d+)?)(h|m|s)", value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        raise ValueError("JS_RESPONSE_MAX_AGE must be a duration such as 24h or 1h30m")
    seconds = sum(
        float(number) * {"h": 3600, "m": 60, "s": 1}[unit] for number, unit in parts
    )
    if not 0 < seconds < float("inf"):
        raise ValueError("JS_RESPONSE_MAX_AGE must be positive and finite")
    return seconds


@dataclass
class Config:
    servers: list[str]
    encrypted: bool
    connect_options: dict
    max_ack_pending: int = 20000
    response_max_age: float = 86400

    @classmethod
    def from_env(cls):
        servers = [
            s.strip() for s in os.getenv("NATS_SERVERS", "").split(",") if s.strip()
        ]
        if not servers:
            raise ValueError("NATS_SERVERS is required")
        ca = os.getenv("PUDA_NATS_CA", "").strip()
        key = os.getenv("PUDA_E2E_KEY_FILE", "").strip()
        if bool(ca) != bool(key):
            raise ValueError("Set both PUDA_NATS_CA and PUDA_E2E_KEY_FILE, or neither")
        encrypted = bool(ca)
        scheme = "tls://" if encrypted else "nats://"
        if any(not s.startswith(scheme) for s in servers):
            raise ValueError(
                f"This mode requires all NATS_SERVERS URLs to use {scheme}"
            )
        if encrypted:
            if not Path(ca).is_file() or not Path(key).is_file():
                raise ValueError(
                    "PUDA_NATS_CA and PUDA_E2E_KEY_FILE must reference existing files"
                )
            try:
                if e2e.reload() is None:
                    raise ValueError("no encrypt key")
            except Exception:
                raise ValueError(
                    "PUDA_E2E_KEY_FILE must contain a valid encrypt key"
                ) from None
            if not os.access(key, os.W_OK) or not os.access(Path(key).parent, os.W_OK):
                raise ValueError(
                    "Key file and its directory must be writable for key rotation"
                )
        else:
            e2e.set_ring(None)
        try:
            options = e2e.connect_kwargs(servers)
        except Exception:
            raise ValueError("Cannot load NATS TLS CA certificate") from None
        try:
            max_pending = int(os.getenv("JS_MAX_ACK_PENDING", "20000"))
            if max_pending <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("JS_MAX_ACK_PENDING must be a positive integer") from None
        max_age = duration_seconds(os.getenv("JS_RESPONSE_MAX_AGE", "24h"))
        return cls(servers, encrypted, options, max_pending, max_age)


def timestamp_ns(value):
    if value is None:
        return time.time_ns()
    if not isinstance(value, str):
        raise ValueError("timestamp must be RFC3339")
    match = re.fullmatch(r"(.{19})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})", value)
    if not match:
        raise ValueError("timestamp must be RFC3339")
    dt = datetime.fromisoformat(match[1] + match[3].replace("Z", "+00:00"))
    seconds = calendar.timegm(dt.utctimetuple())
    return seconds * 1_000_000_000 + int((match[2] or "").ljust(9, "0"))


def tag_value(value):
    text = str(value)
    if any(c in text for c in "\r\n"):
        raise ValueError("invalid tag characters")
    return (
        text.replace("\\", "\\\\")
        .replace(" ", "\\ ")
        .replace(",", "\\,")
        .replace("=", "\\=")
    )


def field_value(value):
    if isinstance(value, str):
        return (
            '"'
            + value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            + '"'
        )
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and math.isfinite(value):
        # json_v2's untyped JSON numbers are floats; step_number is handled separately.
        return repr(float(value))
    raise ValueError("unsupported field value")


def to_line(subject: str, payload: bytes) -> str:
    """Map raw PUDA wire payloads to Influx measurements."""
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("payload must be an object")
    parts = subject.split(".")
    if len(parts) < 4 or parts[0] != "puda":
        raise ValueError("unsupported subject")
    tags = {"subject": subject}
    # Match the SDK's exact {timestamp, data} telemetry envelope only. Keep
    # legacy flattened objects with a data measurement and siblings intact.
    if set(data) == {"timestamp", "data"} and isinstance(data["data"], dict):
        values = data["data"]
    else:
        values = data
    if parts[2:] == ["tlm", "health"]:
        measurement = "telemetry"
        tags["machine_id"] = parts[1]
        fields = {}
        for name in ("cpu", "mem", "temp"):
            value = values.get(name)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                fields[name] = field_value(float(value))
        if isinstance(values.get("status"), str) and values["status"]:
            tags["status"] = values["status"]
        if not fields:
            fields["data"] = field_value(payload.decode("utf-8"))
        timestamp = timestamp_ns(data.get("timestamp"))
    elif len(parts) >= 5 and parts[2:4] == ["tlm", "stream"]:
        measurement = "telemetry_stream"
        tags.update(machine_id=parts[1], stream=".".join(parts[4:]))
        fields = {
            "data": field_value(json.dumps(values, separators=(",", ":"), allow_nan=False))
        }
        timestamp = timestamp_ns(data.get("timestamp"))
    else:
        if parts[2:] not in (
            ["cmd", "queue"],
            ["cmd", "immediate"],
            ["cmd", "response", "queue"],
            ["cmd", "response", "immediate"],
        ):
            raise ValueError("unsupported command subject")
        measurement = "commands"
        response = len(parts) == 5
        header, command = data["header"], data["command"]
        if not isinstance(header, dict) or not isinstance(command, dict):
            raise ValueError("header and command must be objects")
        tags.update(
            machine_id=header["machine_id"],
            cmd_name=command["name"],
            topic=".".join(parts[3:]),
            msg_type="response" if response else "command",
        )
        for name in ("run_id", "username"):
            value = header.get(name)
            if value is not None:
                tags[name] = value
        step = command["step_number"]
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or not -(2**63) <= step < 2**63
        ):
            raise ValueError("step_number must be an int64")
        fields = {"step_number": f"{step}i"}
        for name, value in (
            ("user_id", header.get("user_id")),
            ("cmd_version", command.get("version")),
        ):
            if value is not None:
                fields[name] = field_value(value)
        if response:
            result = data["response"]
            if not isinstance(result, dict):
                raise ValueError("response must be an object")
            if result.get("status") is not None:
                tags["status"] = result["status"]
            for source, target in (
                ("code", "response_code"),
                ("message", "response_message"),
                ("completed_at", "completed_at"),
            ):
                value = result.get(source)
                if source == "message" and value in (None, ""):
                    extra = result.get("data")
                    if extra not in (None, "", "null"):
                        value = (
                            extra
                            if isinstance(extra, str)
                            else json.dumps(extra, separators=(",", ":"))
                        )
                if value is not None:
                    fields[target] = field_value(
                        str(value) if source == "code" else value
                    )
        else:
            tags["status"] = "sent"
        timestamp = timestamp_ns(header["timestamp"])
    tag_text = ",".join(
        f"{key}={tag_value(value)}"
        for key, value in sorted(tags.items())
        if value != ""
    )
    field_text = ",".join(
        f"{tag_value(key)}={value}" for key, value in sorted(fields.items())
    )
    return f"{measurement},{tag_text} {field_text} {timestamp}"


class Subscriber:
    def __init__(self, config):
        self.config = config
        self.nc = None
        self.js = None
        self.queue = asyncio.Queue(maxsize=128)
        self.key_lock = asyncio.Lock()

    async def sync_keyring(self):
        if not self.config.encrypted:
            return
        async with self.key_lock:
            try:
                kv = await self.js.key_value(e2e.KEYRING_BUCKET)
            except NotFoundError:
                return
            try:
                entry = await kv.get(e2e.KEYRING_KEY)
            except NotFoundError:
                e2e.drop_previous()
                return
            plain = e2e.open_payload(
                e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), entry.value
            )
            e2e.adopt_record(plain)

    async def watch_keys(self):
        while True:
            await asyncio.sleep(2)
            try:
                await self.sync_keyring()
            except Exception as exc:
                log.error(
                    "Keyring refresh failed (%s); retaining current keys",
                    type(exc).__name__,
                )
                await asyncio.sleep(8)

    async def ensure_streams(self):
        for name, subject in RESPONSE_STREAMS.items():
            try:
                info = await self.js.stream_info(name)
            except NotFoundError:
                await self.js.add_stream(
                    config=StreamConfig(
                        name=name,
                        subjects=[subject],
                        retention=RetentionPolicy.LIMITS,
                        max_age=self.config.response_max_age,
                    )
                )
            else:
                if subject not in (info.config.subjects or []):
                    raise ValueError(
                        f"{name} does not include the expected response subject"
                    )
                if (
                    info.config.retention != RetentionPolicy.LIMITS
                    or info.config.max_age != self.config.response_max_age
                ):
                    await self.js.update_stream(
                        config=replace(
                            info.config,
                            retention=RetentionPolicy.LIMITS,
                            max_age=self.config.response_max_age,
                        )
                    )
            consumer = RESPONSE_CONSUMERS[name]
            try:
                info = await self.js.consumer_info(name, consumer)
            except NotFoundError:
                config = ConsumerConfig(
                    durable_name=consumer,
                    deliver_group=consumer,
                    deliver_subject=f"puda.logger.influxdb.deliver.{name.lower()}",
                    filter_subject=subject,
                    ack_policy=AckPolicy.EXPLICIT,
                    deliver_policy=DeliverPolicy.ALL,
                    ack_wait=60,
                    max_deliver=5,
                    max_ack_pending=self.config.max_ack_pending,
                )
            else:
                config = info.config
                if (
                    config.deliver_group != consumer
                    or config.filter_subject != subject
                    or not config.deliver_subject
                    or config.ack_policy != AckPolicy.EXPLICIT
                ):
                    raise ValueError(
                        f"Incompatible existing response consumer {consumer}"
                    )
                config = replace(
                    config,
                    ack_wait=60,
                    max_deliver=5,
                    max_ack_pending=self.config.max_ack_pending,
                )
            # Updating the existing durable preserves its delivery subject and cursor.
            await self.js.add_consumer(name, config=config)

    async def maintenance(self, healthcheck=False):
        async with await nats.connect(
            servers=self.config.servers, **self.config.connect_options
        ) as nc:
            self.nc = nc
            self.js = nc.jetstream()
            if healthcheck:
                for stream, consumer in RESPONSE_CONSUMERS.items():
                    info = await self.js.consumer_info(stream, consumer)
                    if (
                        info.config.max_ack_pending > 0
                        and info.num_ack_pending >= info.config.max_ack_pending
                    ):
                        raise ValueError(
                            f"Response consumer {consumer} acknowledgment window saturated"
                        )
            else:
                await self.ensure_streams()

    async def receive(self, msg):
        await self.queue.put((msg, False))

    async def receive_response(self, msg):
        await self.queue.put((msg, True))

    async def process(self, msg, jetstream=False):
        try:
            try:
                plain = e2e.open_payload(msg.subject, msg.data)
            except e2e.E2EError:
                # A newly rotated message may arrive before the periodic keyring refresh.
                await self.sync_keyring()
                plain = e2e.open_payload(msg.subject, msg.data)
        except Exception as exc:
            log.error(
                "Cannot decrypt message on %s (%s)", msg.subject, type(exc).__name__
            )
            if jetstream:
                await msg.nak(delay=5)
            return
        try:
            line = to_line(msg.subject, plain)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            log.error("Invalid message on %s (%s)", msg.subject, type(exc).__name__)
            if jetstream:
                await msg.term()
            return
        # Await the pipe write without blocking NATS heartbeats/keyring polling.
        await asyncio.to_thread(self.emit, line)
        if jetstream:
            await msg.ack()

    @staticmethod
    def emit(line):
        print(line, flush=True)

    async def worker(self):
        while True:
            msg, jetstream = await self.queue.get()
            try:
                await self.process(msg, jetstream)
            finally:
                self.queue.task_done()

    async def run(self):
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        async def on_error(exc):
            log.error("NATS error (%s)", type(exc).__name__)

        async def disconnected():
            log.warning("NATS disconnected; reconnecting")

        async def reconnected():
            log.info("NATS reconnected")

        async def closed():
            stop.set()

        tasks = []
        subscriptions = []
        try:
            self.nc = await nats.connect(
                servers=self.config.servers,
                name="puda-influxdb-logger",
                max_reconnect_attempts=-1,
                error_cb=on_error,
                disconnected_cb=disconnected,
                reconnected_cb=reconnected,
                closed_cb=closed,
                **self.config.connect_options,
            )
            self.js = self.nc.jetstream()
            await self.ensure_streams()
            await self.sync_keyring()
            worker = asyncio.create_task(self.worker())
            tasks.append(worker)
            if self.config.encrypted:
                tasks.append(asyncio.create_task(self.watch_keys()))
            limits = dict(
                pending_msgs_limit=self.config.max_ack_pending,
                pending_bytes_limit=64 * 1024 * 1024,
            )
            # Core subscriptions never attach to the machines' WorkQueue consumers.
            for subject, group in (
                ("puda.*.cmd.queue", "puda_logger_cmd_requests"),
                ("puda.*.cmd.immediate", "puda_logger_cmd_requests"),
                ("puda.*.tlm.health", "puda_logger_telemetry"),
                ("puda.*.tlm.stream.>", "puda_logger_telemetry_stream"),
            ):
                subscriptions.append(
                    await self.nc.subscribe(
                        subject, queue=group, cb=self.receive, **limits
                    )
                )
            for stream, subject in RESPONSE_STREAMS.items():
                subscriptions.append(
                    await self.js.subscribe(
                        subject,
                        stream=stream,
                        durable=RESPONSE_CONSUMERS[stream],
                        queue=RESPONSE_CONSUMERS[stream],
                        cb=self.receive_response,
                        manual_ack=True,
                        **limits,
                    )
                )
            await self.nc.flush()
            log.info(
                "Subscriber ready (%s)",
                "E2EE" if self.config.encrypted else "plaintext",
            )
            waiter = asyncio.create_task(stop.wait())
            tasks.append(waiter)
            done, _ = await asyncio.wait(
                [worker, waiter], return_when=asyncio.FIRST_COMPLETED
            )
            if worker in done:
                await worker
            async with asyncio.timeout(10):
                for subscription in subscriptions:
                    await subscription.drain()
                await self.queue.join()
                await self.nc.drain()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.nc is not None and not self.nc.is_closed:
                await self.nc.close()


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname).1s! %(message)s", stream=sys.stderr
    )
    try:
        config = Config.from_env()
    except Exception as exc:
        log.error("%s", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        return 1
    if "--check-config" not in sys.argv:
        try:
            subscriber = Subscriber(config)
            if "--healthcheck" in sys.argv:
                asyncio.run(subscriber.maintenance(healthcheck=True))
            elif "--init-streams" in sys.argv:
                asyncio.run(subscriber.maintenance())
            else:
                asyncio.run(subscriber.run())
        except Exception as exc:
            log.error("Subscriber stopped (%s)", type(exc).__name__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
