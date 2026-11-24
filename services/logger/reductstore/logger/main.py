"""
Logger service that listens to NATS command, response, and telemetry
subjects and writes them to ReductStore.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg
from nats.errors import NotJSMessageError

from reduct_client import ENTRY_COMMANDS, ENTRY_TELEMETRY, ReductClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

NAMESPACE = "puda"
CMD_REQUEST_SUBJECT = f"{NAMESPACE}.*.cmd.*"
TELEMETRY_SUBJECT = f"{NAMESPACE}.*.tlm.health"
RESPONSE_QUEUE_SUBJECT = f"{NAMESPACE}.*.cmd.response.queue"
RESPONSE_IMMEDIATE_SUBJECT = f"{NAMESPACE}.*.cmd.response.immediate"

STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"

QUEUE_CMD_REQUESTS = "reductstore_logger_cmd_requests"
QUEUE_TELEMETRY = "reductstore_logger_telemetry"
DURABLE_RESP_QUEUE = "reductstore_logger_resp_queue"
DURABLE_RESP_IMMEDIATE = "reductstore_logger_resp_immediate"


def get_required_env(key: str) -> str:
    value = os.getenv(key)
    if value is None or value == "":
        raise ValueError(f"Required environment variable '{key}' is not set")
    return value


NATS_SERVERS = [
    server.strip()
    for server in get_required_env("NATS_SERVERS").split(",")
    if server.strip()
]
REDUCTSTORE_URL = os.getenv("REDUCTSTORE_URL", "http://localhost:8383")
REDUCTSTORE_TOKEN = os.getenv("REDUCTSTORE_TOKEN", "reduct")
REDUCTSTORE_BUCKET = os.getenv("REDUCTSTORE_BUCKET", "puda")


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


def unwrap_body(payload: dict) -> dict:
    """Prefer the inner `data` object used by the older envelope format."""
    data = payload.get("data")
    if isinstance(data, dict) and (
        "header" in data
        or "command" in data
        or "response" in data
        or "cpu" in data
        or "mem" in data
        or "temp" in data
        or "timestamp" in data
    ):
        return data
    return payload


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


class LoggerService:
    """Subscribe to PUDA NATS traffic and persist it in ReductStore."""

    def __init__(self) -> None:
        self.nc = NATS()
        self.db = ReductClient(
            url=REDUCTSTORE_URL,
            token=REDUCTSTORE_TOKEN,
            bucket=REDUCTSTORE_BUCKET,
        )

    async def start(self) -> None:
        await self.db.connect()
        await self.nc.connect(
            servers=NATS_SERVERS,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
            disconnected_cb=self._on_disconnected,
            reconnected_cb=self._on_reconnected,
            error_cb=self._on_error,
        )
        logger.info("Connected to NATS at %s", ", ".join(NATS_SERVERS))
        await self._subscribe()

    async def stop(self) -> None:
        if self.nc.is_connected:
            await self.nc.drain()
        await self.db.close()
        logger.info("Disconnected from NATS and ReductStore")

    async def _subscribe(self) -> None:
        # Command requests use a core subscription so this logger does not
        # compete with the machine's WorkQueue JetStream consumer.
        await self.nc.subscribe(
            CMD_REQUEST_SUBJECT,
            queue=QUEUE_CMD_REQUESTS,
            cb=self._on_command_request,
        )
        await self.nc.subscribe(
            TELEMETRY_SUBJECT,
            queue=QUEUE_TELEMETRY,
            cb=self._on_telemetry,
        )

        js = self.nc.jetstream()
        await js.subscribe(
            RESPONSE_QUEUE_SUBJECT,
            stream=STREAM_RESPONSE_QUEUE,
            durable=DURABLE_RESP_QUEUE,
            queue=DURABLE_RESP_QUEUE,
            manual_ack=True,
            cb=self._on_response,
        )
        await js.subscribe(
            RESPONSE_IMMEDIATE_SUBJECT,
            stream=STREAM_RESPONSE_IMMEDIATE,
            durable=DURABLE_RESP_IMMEDIATE,
            queue=DURABLE_RESP_IMMEDIATE,
            manual_ack=True,
            cb=self._on_response,
        )
        logger.info(
            "Subscribed to %s, %s, %s, %s",
            CMD_REQUEST_SUBJECT,
            TELEMETRY_SUBJECT,
            RESPONSE_QUEUE_SUBJECT,
            RESPONSE_IMMEDIATE_SUBJECT,
        )

    async def _on_command_request(self, msg: Msg) -> None:
        await self._write_command(msg, msg_type="command", default_status="sent")

    async def _on_response(self, msg: Msg) -> None:
        await self._write_command(msg, msg_type="response")

    async def _on_telemetry(self, msg: Msg) -> None:
        ok = False
        try:
            payload = self._decode_json(msg)
            if (
                isinstance(payload, dict)
                and set(payload) == {"timestamp", "data"}
                and isinstance(payload["data"], dict)
            ):
                body = payload["data"]
                time_value = payload["timestamp"]
            else:
                body = unwrap_body(payload) if isinstance(payload, dict) else {}
                time_value = body.get("timestamp")
            timestamp = parse_iso_timestamp(time_value) or datetime.now(timezone.utc)
            labels = {
                "machine_id": machine_id_from_subject(msg.subject)
                or body.get("machine_id"),
                "subject": msg.subject,
            }
            for field in ("cpu", "mem", "temp", "connected", "status"):
                value = body.get(field)
                if value is not None:
                    labels[field] = value
            await self.db.write(ENTRY_TELEMETRY, msg.data, timestamp, labels)
            ok = True
        except Exception:
            logger.exception("Failed to log telemetry from %s", msg.subject)
        await self._finish(msg, ok)

    async def _write_command(
        self,
        msg: Msg,
        msg_type: str,
        default_status: Optional[str] = None,
    ) -> None:
        ok = False
        try:
            payload = self._decode_json(msg)
            body = unwrap_body(payload) if isinstance(payload, dict) else {}
            header = body.get("header") if isinstance(body.get("header"), dict) else {}
            command = (
                body.get("command") if isinstance(body.get("command"), dict) else {}
            )
            response = (
                body.get("response") if isinstance(body.get("response"), dict) else {}
            )

            timestamp = (
                parse_iso_timestamp(header.get("timestamp"))
                or parse_iso_timestamp(payload.get("timestamp") if isinstance(payload, dict) else None)
                or datetime.now(timezone.utc)
            )
            labels = {
                "machine_id": header.get("machine_id")
                or machine_id_from_subject(msg.subject),
                "topic": topic_from_subject(msg.subject),
                "cmd_name": command.get("name"),
                "msg_type": msg_type,
                "status": response.get("status") or default_status,
                "username": header.get("username"),
                "run_id": header.get("run_id"),
                "subject": msg.subject,
                "user_id": header.get("user_id"),
                "step_number": command.get("step_number"),
                "cmd_version": command.get("version"),
            }
            if msg_type == "response":
                labels["response_code"] = response.get("code")
                labels["completed_at"] = response.get("completed_at")
                response_text = response_column_value(response)
                if response_text:
                    labels["response"] = response_text

            await self.db.write(ENTRY_COMMANDS, msg.data, timestamp, labels)
            ok = True
        except Exception:
            logger.exception("Failed to log %s from %s", msg_type, msg.subject)
        await self._finish(msg, ok)

    def _decode_json(self, msg: Msg) -> Any:
        try:
            return json.loads(msg.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.error("Failed to parse message on %s: %s", msg.subject, exc)
            return {}

    async def _finish(self, msg: Msg, ok: bool) -> None:
        # Only JetStream deliveries are acked. Core command requests (including
        # `puda.<id>.cmd.ping`) carry the requester's reply inbox; acking them
        # would send +ACK/-NAK to the CLI ahead of the machine's real reply.
        if not (msg.reply or "").startswith("$JS.ACK."):
            return
        try:
            if ok:
                await msg.ack()
            else:
                await msg.nak()
        except NotJSMessageError:
            return

    async def _on_disconnected(self) -> None:
        logger.warning("Disconnected from NATS")

    async def _on_reconnected(self) -> None:
        logger.info("Reconnected to NATS")

    async def _on_error(self, exc: Exception) -> None:
        logger.error("NATS error: %s", exc)


async def main() -> None:
    service = LoggerService()
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
