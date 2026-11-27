"""
Logger service that listens to NATS command, response, and telemetry
subjects and writes them to ReductStore.

Speaks PUDA Edge Protocol 1.0 (docs/edge-protocol/edge-protocol-v1.0.md) as
an observer: it never subscribes to `cmd.immediate`, `cmd.ping` or `update`,
and never updates or deletes the provisioned response streams.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg
from nats.errors import NotJSMessageError
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.errors import NotFoundError
from puda import e2e

from reduct_client import ENTRY_COMMANDS, ENTRY_TELEMETRY, ReductClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

NAMESPACE = "puda"
# Queued requests only. Immediate commands are recorded from RESPONSE_IMMEDIATE:
# subscribing to cmd.immediate would create interest and stop the broker from
# answering "no responders" for offline machines (spec §8.3).
CMD_QUEUE_SUBJECT = f"{NAMESPACE}.*.cmd.queue"
TELEMETRY_HEALTH_SUBJECT = f"{NAMESPACE}.*.tlm.health"
TELEMETRY_STREAM_SUBJECT = f"{NAMESPACE}.*.tlm.stream.>"
RESPONSE_QUEUE_SUBJECT = f"{NAMESPACE}.*.cmd.response.queue"
RESPONSE_IMMEDIATE_SUBJECT = f"{NAMESPACE}.*.cmd.response.immediate"

STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"
RESPONSE_STREAMS = {
    STREAM_RESPONSE_QUEUE: RESPONSE_QUEUE_SUBJECT,
    STREAM_RESPONSE_IMMEDIATE: RESPONSE_IMMEDIATE_SUBJECT,
}
# Provisioned response stream settings (spec §5).
RESPONSE_STREAM_MAX_AGE = 24 * 3600  # seconds

QUEUE_CMD_REQUESTS = "reductstore_logger_cmd_requests"
QUEUE_TELEMETRY = "reductstore_logger_telemetry"
QUEUE_TELEMETRY_STREAM = "reductstore_logger_telemetry_stream"
DURABLE_RESP_QUEUE = "reductstore_logger_resp_queue"
DURABLE_RESP_IMMEDIATE = "reductstore_logger_resp_immediate"
RESPONSE_CONSUMERS = {
    STREAM_RESPONSE_QUEUE: DURABLE_RESP_QUEUE,
    STREAM_RESPONSE_IMMEDIATE: DURABLE_RESP_IMMEDIATE,
}

KEYRING_POLL_SECONDS = 2
# machine_id and telemetry stream names (spec §3, §12); safe as entry names.
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


@dataclass
class Config:
    servers: list[str]
    encrypted: bool
    connect_options: dict
    reductstore_url: str = "http://localhost:8383"
    reductstore_token: str = "reduct"
    reductstore_bucket: str = "puda"
    # Payload keys loaded once from PUDA_E2E_KEY_FILE; disabled in plaintext mode.
    context: e2e.Context = field(default_factory=e2e.Context)

    @classmethod
    def from_env(cls) -> "Config":
        servers = [
            s.strip() for s in os.getenv("NATS_SERVERS", "").split(",") if s.strip()
        ]
        if not servers:
            raise ValueError("Required environment variable 'NATS_SERVERS' is not set")
        ca = os.getenv("PUDA_NATS_CA", "").strip()
        key = os.getenv("PUDA_E2E_KEY_FILE", "").strip()
        if bool(ca) != bool(key):
            raise ValueError("Set both PUDA_NATS_CA and PUDA_E2E_KEY_FILE, or neither")
        encrypted = bool(ca)
        scheme = "tls://" if encrypted else "nats://"
        if any(not s.startswith(scheme) for s in servers):
            raise ValueError(f"This mode requires all NATS_SERVERS URLs to use {scheme}")
        if encrypted:
            if not Path(ca).is_file() or not Path(key).is_file():
                raise ValueError(
                    "PUDA_NATS_CA and PUDA_E2E_KEY_FILE must reference existing files"
                )
            try:
                context = e2e.Context(key)
            except Exception:
                raise ValueError(
                    "PUDA_E2E_KEY_FILE must contain a valid encrypt key"
                ) from None
            if not os.access(key, os.W_OK) or not os.access(Path(key).parent, os.W_OK):
                raise ValueError(
                    "Key file and its directory must be writable for key rotation"
                )
        else:
            context = e2e.Context()
        try:
            options = e2e.connect_kwargs(servers, ca or None)
        except Exception:
            raise ValueError("Cannot load NATS TLS CA certificate") from None
        return cls(
            servers=servers,
            encrypted=encrypted,
            connect_options=options,
            reductstore_url=os.getenv("REDUCTSTORE_URL", "http://localhost:8383"),
            reductstore_token=os.getenv("REDUCTSTORE_TOKEN", "reduct"),
            reductstore_bucket=os.getenv("REDUCTSTORE_BUCKET", "puda"),
            context=context,
        )


class InvalidMessage(ValueError):
    """A payload that does not match the protocol 1.0 shape; logged and dropped."""


def parse_iso_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, including nanosecond fractions."""
    if not isinstance(value, str) or not value:
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    # Trim fractional seconds to microseconds when the payload has nanos.
    if "." in text:
        head, rest = text.split(".", 1)
        digits = ""
        tz_part = ""
        for index, char in enumerate(rest):
            if char.isdigit():
                digits += char
            else:
                tz_part = rest[index:]
                break
        text = f"{head}.{digits[:6]}{tz_part}"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def machine_id_from_subject(subject: str) -> Optional[str]:
    parts = subject.split(".")
    if len(parts) >= 2 and parts[0] == NAMESPACE:
        return parts[1]
    return None


def topic_from_subject(subject: str) -> Optional[str]:
    """puda.first.cmd.response.queue -> response.queue"""
    marker = ".cmd."
    index = subject.find(marker)
    if index == -1:
        return None
    return subject[index + len(marker) :]


def stream_name_from_subject(subject: str) -> Optional[str]:
    """puda.first.tlm.stream.pos -> pos"""
    parts = subject.split(".")
    if len(parts) == 5 and parts[0] == NAMESPACE and parts[2:4] == ["tlm", "stream"]:
        return parts[4]
    return None


def telemetry_stream_entry(machine_id: str, stream: str) -> str:
    """One ReductStore entry per machine and telemetry stream."""
    return f"stream__{machine_id}__{stream}"


def unwrap_telemetry(payload: Any) -> tuple[datetime, dict]:
    """Return (timestamp, data) from the §12 `{timestamp, data}` wrapper."""
    if not isinstance(payload, dict):
        raise InvalidMessage("telemetry must be a JSON object")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise InvalidMessage("telemetry must use the {timestamp, data} wrapper")
    timestamp = parse_iso_timestamp(payload.get("timestamp"))
    if timestamp is None:
        raise InvalidMessage("telemetry timestamp must be ISO 8601")
    return timestamp, data


# Grafana's ReductStore plugin only creates columns from JSON *leaves*, so the
# dashboard reads a string label. Same source as the Influx command log:
# response.message, else response.data, else response.code.
# Grafana queries ReductStore in batch form (`key=value,key=value`). Commas in a
# label value split into fake columns and crash the plugin, so replace them.
# Header values must be Latin-1, so use ASCII `;` rather than a Unicode comma.
RESPONSE_LABEL_MAX_CHARS = 4000


def compact_label(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    text = (
        value.replace("\r", " ")
        .replace("\n", " ")
        .replace(",", ";")
        .encode("ascii", "replace")
        .decode("ascii")
    )
    if len(text) > RESPONSE_LABEL_MAX_CHARS:
        text = text[: RESPONSE_LABEL_MAX_CHARS - 1] + "..."
    return text


def response_column_value(response: dict) -> Optional[str]:
    """Match bears-first: COALESCE(response_message, response_code, '')."""
    message = response.get("message")
    if message not in (None, "", "null"):
        return compact_label(message)
    data = response.get("data")
    if data not in (None, "", "null"):
        return compact_label(data)
    code = response.get("code")
    if code not in (None, ""):
        return compact_label(code)
    return None


def command_labels(subject: str, payload: Any, msg_type: str) -> tuple[datetime, dict]:
    """Map a protocol 1.0 command/response envelope (§8.1, §8.4) to labels."""
    if not isinstance(payload, dict):
        raise InvalidMessage("envelope must be a JSON object")
    header = payload.get("header")
    command = payload.get("command")
    if not isinstance(header, dict) or not isinstance(command, dict):
        raise InvalidMessage("envelope requires header and command objects")
    response = payload.get("response")
    if msg_type == "response" and not isinstance(response, dict):
        raise InvalidMessage("response envelope requires a response object")
    response = response if isinstance(response, dict) else {}

    timestamp = parse_iso_timestamp(header.get("timestamp")) or datetime.now(
        timezone.utc
    )
    labels = {
        "machine_id": header.get("machine_id") or machine_id_from_subject(subject),
        "topic": topic_from_subject(subject),
        "cmd_name": command.get("name"),
        "msg_type": msg_type,
        "status": response.get("status") if msg_type == "response" else "sent",
        "protocol_version": header.get("protocol_version"),
        "username": header.get("username"),
        "run_id": header.get("run_id"),
        "subject": subject,
        "user_id": header.get("user_id"),
        "step_number": command.get("step_number"),
    }
    if msg_type == "response":
        labels["response_code"] = response.get("code")
        labels["completed_at"] = response.get("completed_at")
        response_text = response_column_value(response)
        if response_text:
            labels["response"] = response_text
    return timestamp, labels


def is_e2e_frame(data: bytes) -> bool:
    return len(data) >= 34 and data[:2] == b"\xe2\x01"


class LoggerService:
    """Subscribe to PUDA NATS traffic and persist it in ReductStore."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.nc = NATS()
        self.js: Any = None
        self.db = ReductClient(
            url=config.reductstore_url,
            token=config.reductstore_token,
            bucket=config.reductstore_bucket,
        )
        self.key_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        await self.db.connect()
        await self.nc.connect(
            servers=self.config.servers,
            name="puda-reductstore-logger",
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
            disconnected_cb=self._on_disconnected,
            reconnected_cb=self._on_reconnected,
            error_cb=self._on_error,
            **self.config.connect_options,
        )
        logger.info(
            "Connected to NATS at %s (%s)",
            ", ".join(self.config.servers),
            "E2EE" if self.config.encrypted else "plaintext",
        )
        self.js = self.nc.jetstream()
        await self.ensure_streams()
        await self.sync_keyring()
        if self.config.encrypted:
            self._tasks.append(asyncio.create_task(self._watch_keys()))
        await self._subscribe()

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.nc.is_connected:
            await self.nc.drain()
        await self.db.close()
        logger.info("Disconnected from NATS and ReductStore")

    # --- E2E keyring (§13.5) -------------------------------------------------

    async def sync_keyring(self) -> None:
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
                self.config.context.drop_previous()
                return
            plain = self.config.context.open_payload(
                e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), entry.value
            )
            if self.config.context.adopt_record(plain):
                logger.info("Adopted rotated E2E keyring")

    async def _watch_keys(self) -> None:
        while True:
            await asyncio.sleep(KEYRING_POLL_SECONDS)
            try:
                await self.sync_keyring()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Keyring refresh failed (%s); retaining current keys",
                    type(exc).__name__,
                )
                await asyncio.sleep(8)

    # --- JetStream objects (§5) ----------------------------------------------

    async def ensure_streams(self) -> None:
        """Check the response streams; create only missing ones, never update."""
        for name, subject in RESPONSE_STREAMS.items():
            try:
                info = await self.js.stream_info(name)
            except NotFoundError:
                logger.warning(
                    "Stream %s is missing; broker is unprovisioned. Creating it "
                    "with the protocol 1.0 settings",
                    name,
                )
                await self.js.add_stream(
                    config=StreamConfig(
                        name=name,
                        subjects=[subject],
                        retention=RetentionPolicy.INTEREST,
                        storage=StorageType.FILE,
                        max_age=RESPONSE_STREAM_MAX_AGE,
                    )
                )
            else:
                cfg = info.config
                if cfg.retention == RetentionPolicy.WORK_QUEUE:
                    raise ValueError(
                        f"Stream {name} uses workqueue retention; a logger consumer "
                        "would steal responses from clients. Reprovision it with "
                        "interest retention"
                    )
                if (
                    subject not in (cfg.subjects or [])
                    or cfg.retention != RetentionPolicy.INTEREST
                    or cfg.storage != StorageType.FILE
                    or cfg.max_age != RESPONSE_STREAM_MAX_AGE
                ):
                    logger.warning(
                        "Stream %s does not match the provisioned settings "
                        "(subjects=%s retention=%s storage=%s max_age=%s); "
                        "leaving it unchanged",
                        name,
                        cfg.subjects,
                        cfg.retention,
                        cfg.storage,
                        cfg.max_age,
                    )
            await self.ensure_consumer(name, subject)

    async def ensure_consumer(self, stream: str, subject: str) -> ConsumerConfig:
        """Create this logger's durable push consumer if missing and return it."""
        durable = RESPONSE_CONSUMERS[stream]
        try:
            info = await self.js.consumer_info(stream, durable)
        except NotFoundError:
            config = ConsumerConfig(
                durable_name=durable,
                deliver_group=durable,
                deliver_subject=f"reductstore_logger.deliver.{stream.lower()}",
                filter_subject=subject,
                ack_policy=AckPolicy.EXPLICIT,
                deliver_policy=DeliverPolicy.ALL,
            )
            info = await self.js.add_consumer(stream, config=config)
            logger.info("Created durable consumer %s on %s", durable, stream)
        config = info.config
        if (
            config.deliver_group != durable
            or config.filter_subject != subject
            or not config.deliver_subject
            or config.ack_policy != AckPolicy.EXPLICIT
        ):
            raise ValueError(
                f"Incompatible existing consumer {durable} on {stream}; delete it "
                "to let the logger recreate it"
            )
        return config

    # --- Subscriptions -------------------------------------------------------

    async def _subscribe(self) -> None:
        # Core subscriptions: the queued-command subscription observes publishes
        # to COMMAND_QUEUE without competing with the machine's WorkQueue
        # consumer. No cmd.immediate, cmd.ping or update subscriptions (§8.3).
        for subject, group, cb in (
            (CMD_QUEUE_SUBJECT, QUEUE_CMD_REQUESTS, self._on_command_request),
            (TELEMETRY_HEALTH_SUBJECT, QUEUE_TELEMETRY, self._on_telemetry),
            (TELEMETRY_STREAM_SUBJECT, QUEUE_TELEMETRY_STREAM, self._on_telemetry_stream),
        ):
            await self.nc.subscribe(subject, queue=group, cb=cb)

        # Bind to the explicitly created durables; subscribe_bind never creates
        # streams or consumers implicitly.
        for stream, subject in RESPONSE_STREAMS.items():
            config = await self.ensure_consumer(stream, subject)
            await self.js.subscribe_bind(
                stream=stream,
                config=config,
                consumer=RESPONSE_CONSUMERS[stream],
                cb=self._on_response,
                manual_ack=True,
            )
        logger.info(
            "Subscribed to %s, %s, %s, %s, %s",
            CMD_QUEUE_SUBJECT,
            TELEMETRY_HEALTH_SUBJECT,
            TELEMETRY_STREAM_SUBJECT,
            RESPONSE_QUEUE_SUBJECT,
            RESPONSE_IMMEDIATE_SUBJECT,
        )

    async def _on_command_request(self, msg: Msg) -> None:
        await self._write_command(msg, msg_type="command")

    async def _on_response(self, msg: Msg) -> None:
        await self._write_command(msg, msg_type="response")

    async def _on_telemetry(self, msg: Msg) -> None:
        async def write(payload: Any, raw: bytes) -> None:
            timestamp, body = unwrap_telemetry(payload)
            labels = {
                "machine_id": machine_id_from_subject(msg.subject),
                "subject": msg.subject,
            }
            for field_name in ("cpu", "mem", "temp", "status"):
                value = body.get(field_name)
                if value is not None:
                    labels[field_name] = value
            await self.db.write(ENTRY_TELEMETRY, raw, timestamp, labels)

        await self._handle(msg, "telemetry", write)

    async def _on_telemetry_stream(self, msg: Msg) -> None:
        async def write(payload: Any, raw: bytes) -> None:
            machine_id = machine_id_from_subject(msg.subject) or ""
            stream = stream_name_from_subject(msg.subject) or ""
            if not ID_PATTERN.fullmatch(machine_id) or not ID_PATTERN.fullmatch(stream):
                raise InvalidMessage("unsupported telemetry stream subject")
            timestamp, _ = unwrap_telemetry(payload)
            labels = {"machine_id": machine_id, "stream": stream, "subject": msg.subject}
            await self.db.write(
                telemetry_stream_entry(machine_id, stream),
                raw,
                timestamp,
                labels,
            )

        await self._handle(msg, "telemetry stream", write)

    async def _write_command(self, msg: Msg, msg_type: str) -> None:
        async def write(payload: Any, raw: bytes) -> None:
            timestamp, labels = command_labels(msg.subject, payload, msg_type)
            await self.db.write(ENTRY_COMMANDS, raw, timestamp, labels)

        await self._handle(msg, msg_type, write)

    async def _handle(self, msg: Msg, kind: str, write) -> None:
        """Open, decode and store one message; ack/nak/term JetStream deliveries."""
        try:
            plain = await self._open(msg)
        except Exception as exc:
            logger.error(
                "Cannot decrypt %s on %s (%s)", kind, msg.subject, type(exc).__name__
            )
            # A sealed frame may be readable after the next keyring refresh;
            # plaintext-when-keyed (or sealed-without-key) never will be.
            retry = self.config.encrypted and is_e2e_frame(msg.data)
            await self._finish(msg, "nak" if retry else "term")
            return
        try:
            payload = json.loads(plain.decode("utf-8"))
            # Store the opened (plaintext) JSON so records stay readable.
            await write(payload, plain)
        except (UnicodeDecodeError, json.JSONDecodeError, InvalidMessage) as exc:
            logger.error("Dropping invalid %s on %s: %s", kind, msg.subject, exc)
            await self._finish(msg, "term")
            return
        except Exception:
            logger.exception("Failed to log %s from %s", kind, msg.subject)
            await self._finish(msg, "nak")
            return
        await self._finish(msg, "ack")

    async def _open(self, msg: Msg) -> bytes:
        context = self.config.context
        try:
            return context.open_payload(msg.subject, msg.data)
        except e2e.E2EError:
            if not self.config.encrypted:
                raise
            # A newly rotated message may arrive before the periodic refresh.
            await self.sync_keyring()
            return context.open_payload(msg.subject, msg.data)

    async def _finish(self, msg: Msg, action: str) -> None:
        # Only JetStream deliveries are acked. Core messages never carry a
        # JetStream ack subject; replying to them would confuse requesters.
        if not (msg.reply or "").startswith("$JS.ACK."):
            return
        try:
            if action == "ack":
                await msg.ack()
            elif action == "term":
                await msg.term()
            else:
                await msg.nak(delay=5)
        except NotJSMessageError:
            return

    async def _on_disconnected(self) -> None:
        logger.warning("Disconnected from NATS")

    async def _on_reconnected(self) -> None:
        logger.info("Reconnected to NATS")

    async def _on_error(self, exc: Exception) -> None:
        logger.error("NATS error: %s", exc)


async def main() -> None:
    config = Config.from_env()
    service = LoggerService(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await service.start()
    logger.info("reductstore-logger is running")
    await stop.wait()
    await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
