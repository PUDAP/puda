"""
NATS client for machine edge services.

Connects to NATS, publishes telemetry/events, and subscribes to commands.
Subject pattern: puda.{machine_id}.{category}.{sub_category}

Command handling lives on CommandProcessor (command_processor.py). The
puda.{machine_id}.update subject is subscribed by EdgeUpdater.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Awaitable, Callable, Dict, Optional

import nats
from nats.aio.msg import Msg
from nats.js.api import ConsumerConfig, StreamConfig
from nats.js.client import JetStreamContext
from nats.js.errors import Error as NATSError
from nats.js.errors import NotFoundError
from nats.js.kv import KeyValue

from .constants import (
    KV_BUCKET_COMMANDS,
    KV_BUCKET_STATE,
    NAMESPACE,
    STREAM_COMMAND_IMMEDIATE,
    STREAM_COMMAND_QUEUE,
    STREAM_RESPONSE_IMMEDIATE,
    STREAM_RESPONSE_QUEUE,
)
from .command_processor import CommandProcessor
from .models import CommandResponse, MachineState, NATSMessage, _get_current_timestamp

logger = logging.getLogger(__name__)

_REQUIRED_STREAMS = (
    (STREAM_COMMAND_QUEUE, f"{NAMESPACE}.*.cmd.queue", "workqueue"),
    (STREAM_COMMAND_IMMEDIATE, f"{NAMESPACE}.*.cmd.immediate", "workqueue"),
    (STREAM_RESPONSE_QUEUE, f"{NAMESPACE}.*.cmd.response.queue", "interest"),
    (STREAM_RESPONSE_IMMEDIATE, f"{NAMESPACE}.*.cmd.response.immediate", "interest"),
)


def _sdk_version() -> str:
    try:
        return version("puda")
    except PackageNotFoundError:
        return "unknown"


def _normalize_description(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    return collapsed or None


class EdgeNatsClient:
    """
    NATS client used by the machine edge.

    - Telemetry / events: core NATS (fire-and-forget)
    - Commands: JetStream WorkQueue (COMMAND_QUEUE pull, COMMAND_IMMEDIATE push)
    - Command responses: JetStream Interest (RESPONSE_QUEUE, RESPONSE_IMMEDIATE)
    """

    HEARTBEAT_INTERVAL = 5.0  # seconds
    POSITION_INTERVAL = 3.0  # seconds

    def __init__(
        self,
        servers: list[str],
        machine_id: str,
        description: Optional[str] = None,
    ):
        """
        Args:
            servers: NATS server URLs.
            machine_id: Machine identifier (e.g. "opentron").
            description: Optional one-sentence summary advertised on ping.
                EdgeRunner fills this from the driver class docstring when omitted.
        """
        self.servers = servers
        self.machine_id = machine_id
        self.description = _normalize_description(description)
        self.sdk_version = _sdk_version()
        self._started_at = time.monotonic()
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self.kv_state: Optional[KeyValue] = None
        self.kv_commands: Optional[KeyValue] = None
        self.state_handler: Optional[Callable[[], Dict[str, Any]]] = None
        self.runtime_status_handler: Callable[[], str] = lambda: "idle"

        self._init_subjects()

        self._cmd_queue_sub = None
        self._cmd_queue_task = None
        self._cmd_immediate_sub = None
        self._ping_sub: Any = None
        self._ping_broadcast_sub: Any = None

        self._is_connected = False
        self._queue_handler = None
        self._immediate_handler = None

        self._heartbeat_lock = asyncio.Lock()
        self._last_heartbeat_at: float | None = None
        self._position_lock = asyncio.Lock()
        self._last_position_at: float | None = None

        self.commands = CommandProcessor(self)

    def set_state_handler(self, state_handler: Callable[[], Dict[str, Any]] | None) -> None:
        """Set optional machine-specific state fields to include in KV state updates."""
        self.state_handler = state_handler

    def set_runtime_status_handler(self, handler: Callable[[], str]) -> None:
        """Set the in-memory runtime status provider used by ping responses."""
        self.runtime_status_handler = handler

    def set_description(self, description: Optional[str]) -> None:
        """Set the one-sentence summary included in ping pong replies."""
        self.description = _normalize_description(description)

    def _init_subjects(self) -> None:
        mid = self.machine_id.replace(".", "-")
        prefix = f"{NAMESPACE}.{mid}"

        self.tlm_heartbeat = f"{prefix}.tlm.heartbeat"
        self.tlm_pos = f"{prefix}.tlm.pos"
        self.tlm_health = f"{prefix}.tlm.health"

        self.cmd_queue = f"{prefix}.cmd.queue"
        self.cmd_immediate = f"{prefix}.cmd.immediate"
        self.ping = f"{prefix}.cmd.ping"
        self.ping_broadcast = f"{NAMESPACE}.cmd.ping"

        self.response_queue = f"{prefix}.cmd.response.queue"
        self.response_immediate = f"{prefix}.cmd.response.immediate"

        self.evt_log = f"{prefix}.evt.log"
        self.evt_alert = f"{prefix}.evt.alert"
        self.evt_media = f"{prefix}.evt.media"

        self.update = f"{prefix}.update"
        self.update_response = f"{prefix}.update.response"

        self.kv_bucket_state = KV_BUCKET_STATE
        self.kv_bucket_commands = KV_BUCKET_COMMANDS

    _format_timestamp = staticmethod(_get_current_timestamp)

    async def _publish(self, subject: str, data: Dict[str, Any]) -> bool:
        """Publish a timestamped message to core NATS (fire-and-forget)."""
        if not self.nc:
            logger.warning("NATS not connected, skipping %s", subject)
            return False
        try:
            message = {"timestamp": self._format_timestamp(), **data}
            await self.nc.publish(subject=subject, payload=json.dumps(message).encode())
            logger.debug("Published to %s", subject)
            return True
        except Exception as e:
            logger.error("Error publishing to %s: %s", subject, e)
            return False

    async def _publish_throttled(
        self,
        lock: asyncio.Lock,
        last_at: float | None,
        interval: float,
        subject: str,
        data: Dict[str, Any],
    ) -> tuple[bool, float | None]:
        async with lock:
            now = time.monotonic()
            if last_at is not None and now - last_at < interval:
                return False, last_at
            published = await self._publish(subject, data)
            return published, now if published else last_at

    async def _ensure_stream(self, stream_name: str, subject_pattern: str, retention: str) -> None:
        """Create or update a stream so its subject pattern and retention match."""
        if not self.js:
            return
        config = StreamConfig(
            name=stream_name,
            subjects=[subject_pattern],
            retention=retention,
        )
        try:
            stream_info = await self.js.stream_info(stream_name)
            existing = stream_info.config
            if subject_pattern in existing.subjects and getattr(existing, "retention", None) == retention:
                return
            logger.info("Updating %s stream: subject=%s, retention=%s", stream_name, subject_pattern, retention)
            await self.js.update_stream(config=config)
            logger.info("Successfully updated %s stream", stream_name)
        except NotFoundError:
            logger.info("Creating %s stream: subject=%s, retention=%s", stream_name, subject_pattern, retention)
            await self.js.add_stream(config)
            logger.info("Successfully created %s stream", stream_name)
        except Exception as e:
            logger.error("Error ensuring %s stream: %s", stream_name, e, exc_info=True)
            raise

    async def _ensure_all_streams(self) -> None:
        """Ensure streams exist with the subject patterns and retention in infra/nats."""
        for stream_name, subject_pattern, retention in _REQUIRED_STREAMS:
            await self._ensure_stream(stream_name, subject_pattern, retention)

    async def _get_or_create_kv_bucket(self, bucket: str) -> KeyValue:
        if not self.js:
            raise RuntimeError("JetStream not available")
        try:
            return await self.js.create_key_value(bucket=bucket)
        except Exception:
            return await self.js.key_value(bucket)

    async def _safe_unsubscribe(self, sub) -> None:
        if sub is None:
            return
        try:
            await sub.unsubscribe()
        except Exception:
            pass

    async def _cleanup_subscriptions(self) -> None:
        if self._cmd_queue_task:
            self._cmd_queue_task.cancel()
            try:
                await self._cmd_queue_task
            except (asyncio.CancelledError, Exception):
                pass
            self._cmd_queue_task = None

        await self._safe_unsubscribe(self._cmd_queue_sub)
        self._cmd_queue_sub = None
        await self._safe_unsubscribe(self._cmd_immediate_sub)
        self._cmd_immediate_sub = None
        await self._safe_unsubscribe(self._ping_sub)
        self._ping_sub = None
        await self._safe_unsubscribe(self._ping_broadcast_sub)
        self._ping_broadcast_sub = None

    def _reset_connection_state(self) -> None:
        self._is_connected = False
        self.js = None
        self.kv_state = None
        self.kv_commands = None
        self._cmd_queue_sub = None
        self._cmd_queue_task = None
        self._cmd_immediate_sub = None
        self._ping_sub = None
        self._ping_broadcast_sub = None
        self._last_heartbeat_at = None
        self._last_position_at = None

    async def _setup_jetstream(self) -> None:
        self.js = self.nc.jetstream()
        await self._ensure_all_streams()
        self.kv_state = await self._get_or_create_kv_bucket(self.kv_bucket_state)
        self.kv_commands = await self._get_or_create_kv_bucket(self.kv_bucket_commands)

    async def connect(self) -> bool:
        """Connect to NATS and initialize JetStream with auto-reconnection."""
        try:
            self.nc = await nats.connect(
                servers=self.servers,
                connect_timeout=10,
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback,
            )
            await self._setup_jetstream()
            self._is_connected = True
            logger.info("Connected to NATS servers: %s", self.servers)
            return True
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", e)
            self._reset_connection_state()
            return False

    async def _error_callback(self, error: Exception) -> None:
        logger.error("NATS error: %s", error)

    async def _disconnected_callback(self) -> None:
        logger.warning("Disconnected from NATS servers")
        self._reset_connection_state()

    async def _reconnected_callback(self) -> None:
        logger.info("Reconnected to NATS servers")
        self._is_connected = True
        if self.nc:
            await self._setup_jetstream()
            await self._resubscribe_handlers()

    async def _resubscribe_handlers(self) -> None:
        if self._queue_handler:
            await self.subscribe_queue(self._queue_handler)
        if self._immediate_handler:
            await self.subscribe_immediate(self._immediate_handler)

    async def _closed_callback(self) -> None:
        logger.info("NATS connection closed")
        self._reset_connection_state()

    async def disconnect(self) -> None:
        await self._cleanup_subscriptions()
        if self.nc:
            await self.nc.close()
            self._reset_connection_state()
            logger.info("Disconnected from NATS")

    async def subscribe_ping(self) -> None:
        """Subscribe to direct and fleet-wide Core NATS ping subjects."""
        if self.nc is None:
            raise RuntimeError("NATS not connected")
        await self._safe_unsubscribe(self._ping_sub)
        await self._safe_unsubscribe(self._ping_broadcast_sub)
        self._ping_sub = await self.nc.subscribe(subject=self.ping, cb=self._handle_ping)
        self._ping_broadcast_sub = await self.nc.subscribe(
            subject=self.ping_broadcast,
            cb=self._handle_ping,
        )
        await self.nc.flush()
        logger.info(
            "Subscribed to Core NATS ping requests: direct=%s broadcast=%s",
            self.ping,
            self.ping_broadcast,
        )

    async def _handle_ping(self, msg: Msg) -> None:
        """Reply to ping with a structured pong payload."""
        if msg.data.strip().lower() == b"ping":
            payload: dict[str, Any] = {
                "status": "pong",
                "machine_id": self.machine_id,
                "timestamp": self._format_timestamp(),
                "sdk_version": self.sdk_version,
                "uptime_seconds": round(max(0.0, time.monotonic() - self._started_at), 3),
                "run_status": self.runtime_status_handler(),
            }
            if self.description:
                payload["description"] = self.description
        else:
            payload = {
                "status": "error",
                "machine_id": self.machine_id,
                "timestamp": self._format_timestamp(),
                "message": "expected ping",
            }
        try:
            await msg.respond(json.dumps(payload).encode())
        except Exception as e:
            logger.error("Failed to reply to ping on %s: %s", self.ping, e)

    async def publish_heartbeat(self) -> bool:
        """Publish at most one heartbeat every HEARTBEAT_INTERVAL seconds."""
        published, self._last_heartbeat_at = await self._publish_throttled(
            self._heartbeat_lock,
            self._last_heartbeat_at,
            self.HEARTBEAT_INTERVAL,
            self.tlm_heartbeat,
            {},
        )
        return published

    async def publish_position(self, coords: Dict[str, float]) -> bool:
        """Publish position telemetry at most once every POSITION_INTERVAL seconds."""
        published, self._last_position_at = await self._publish_throttled(
            self._position_lock,
            self._last_position_at,
            self.POSITION_INTERVAL,
            self.tlm_pos,
            coords,
        )
        return published

    async def publish_health(self, vitals: Dict[str, Any]) -> None:
        """Publish system health vitals (CPU, memory, temperature, etc.)."""
        await self._publish(self.tlm_health, vitals)

    async def publish_state(self, data: Dict[str, Any]) -> None:
        """Overwrite machine state in the NATS KV store."""
        if not self.kv_state:
            logger.warning("KV store not available, skipping state update")
            return
        try:
            message = {"timestamp": self._format_timestamp(), **data}
            if self.state_handler is not None:
                message.update(self.state_handler())
            if isinstance(message.get("state"), MachineState):
                message["state"] = message["state"].value
            await self.kv_state.put(self.machine_id, json.dumps(message).encode())
            logger.info("Updated state in KV store: %s", message)
        except Exception as e:
            logger.error("Error updating status in KV store: %s", e)

    async def publish_commands(self, data: Dict[str, Any]) -> None:
        """Publish the command catalog to the KV store."""
        if not self.kv_commands:
            logger.warning("KV store not available, skipping command update")
            return
        try:
            await self.kv_commands.put(self.machine_id, json.dumps(data).encode())
            logger.info("Published commands to KV store")
        except Exception as e:
            logger.error("Error publishing command to KV store: %s", e)

    async def _delete_consumer(self, stream: str, durable_name: str, *, retry_if_bound: bool = False) -> None:
        try:
            await self.js.delete_consumer(stream, durable_name)
            logger.info("Deleted consumer: %s", durable_name)
        except NotFoundError:
            logger.debug("Consumer %s does not exist, will be created", durable_name)
        except Exception as e:
            error_msg = str(e).lower()
            if retry_if_bound and ("bound" in error_msg or "in use" in error_msg):
                logger.warning("Consumer %s is bound. Retrying delete...", durable_name)
                await asyncio.sleep(0.5)
                try:
                    await self.js.delete_consumer(stream, durable_name)
                    logger.info("Deleted bound consumer: %s", durable_name)
                except Exception as delete_error:
                    logger.warning("Could not delete bound consumer %s: %s", durable_name, delete_error)
            else:
                logger.warning("Error deleting consumer %s: %s", durable_name, e)

    async def _verify_or_recreate_consumer(self, durable_name: str) -> None:
        """Delete the durable consumer if its config does not match this machine."""
        try:
            info = await self.js.consumer_info(STREAM_COMMAND_QUEUE, durable_name)
            config = info.config
            expected = {
                "filter_subject": self.cmd_queue,
                "ack_policy": "explicit",
                "deliver_policy": "all",
            }
            mismatches = [
                attr for attr, want in expected.items() if getattr(config, attr, None) != want
            ]
            if mismatches:
                logger.info("Consumer config mismatch (%s), recreating: %s", mismatches, durable_name)
                await self._delete_consumer(STREAM_COMMAND_QUEUE, durable_name)
            else:
                logger.info(
                    "Consumer exists with correct config - pending: %d, delivered: %d, ack_pending: %d",
                    info.num_pending,
                    info.delivered.consumer_seq,
                    info.num_ack_pending,
                )
        except NotFoundError:
            logger.debug("Durable consumer %s does not exist, will be created", durable_name)

    async def _pull_queue_loop(self, handler: Callable[[NATSMessage], Awaitable[CommandResponse]]) -> None:
        try:
            while True:
                try:
                    msgs = await self._cmd_queue_sub.fetch(batch=1, timeout=1.0)
                    if msgs:
                        logger.debug("Pulled message from queue")
                        await self.commands.process_queue(msgs[0], handler)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error("Error pulling queue messages: %s", e, exc_info=True)
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.debug("Queue pull task cancelled")
            raise

    async def subscribe_queue(self, handler: Callable[[NATSMessage], Awaitable[CommandResponse]]) -> None:
        """Subscribe to queue commands with a durable pull consumer."""
        if not self.js:
            logger.error("JetStream not available for queue subscription")
            return

        self._queue_handler = handler
        await self._ensure_all_streams()
        durable_name = f"cmd_queue_{self.machine_id}"
        await self._verify_or_recreate_consumer(durable_name)

        try:
            self._cmd_queue_sub = await self.js.pull_subscribe(
                subject=self.cmd_queue,
                durable=durable_name,
                stream=STREAM_COMMAND_QUEUE,
                config=ConsumerConfig(
                    durable_name=durable_name,
                    filter_subject=self.cmd_queue,
                    ack_policy="explicit",
                    deliver_policy="all",
                ),
            )
            try:
                info = await self.js.consumer_info(STREAM_COMMAND_QUEUE, durable_name)
                logger.info(
                    "Pull subscription created - subject: %s, durable: %s, pending: %d, ack_pending: %d",
                    self.cmd_queue, durable_name, info.num_pending, info.num_ack_pending,
                )
            except Exception as e:
                logger.warning("Could not get consumer info after subscription: %s", e)

            self._cmd_queue_task = asyncio.create_task(self._pull_queue_loop(handler))
            logger.info("Started background task for pulling queue messages")
        except NotFoundError:
            logger.error(
                "Stream %s not found when subscribing to %s (pattern %s.*.cmd.queue)",
                STREAM_COMMAND_QUEUE, self.cmd_queue, NAMESPACE,
            )
            raise

        logger.info(
            "Subscribed to queue commands: %s (durable: %s, pull consumer)",
            self.cmd_queue, durable_name,
        )

    async def subscribe_immediate(self, handler: Callable[[NATSMessage], Awaitable[CommandResponse]]) -> None:
        """Subscribe to immediate commands with a durable push consumer."""
        if not self.js:
            logger.error("JetStream not available for immediate subscription")
            return

        self._immediate_handler = handler
        await self._ensure_all_streams()
        durable_name = f"cmd_immed_{self.machine_id}"

        async def message_handler(msg: Msg) -> None:
            await self.commands.process_immediate(msg, self._immediate_handler)

        await self._safe_unsubscribe(self._cmd_immediate_sub)
        self._cmd_immediate_sub = None
        await self._delete_consumer(STREAM_COMMAND_IMMEDIATE, durable_name, retry_if_bound=True)

        try:
            self._cmd_immediate_sub = await self.js.subscribe(
                subject=self.cmd_immediate,
                stream=STREAM_COMMAND_IMMEDIATE,
                durable=durable_name,
                cb=message_handler,
            )
        except NATSError as e:
            error_msg = str(e).lower()
            if "bound" not in error_msg and "already bound" not in error_msg:
                raise
            logger.warning("Consumer %s still bound. Deleting and retrying...", durable_name)
            await self._delete_consumer(STREAM_COMMAND_IMMEDIATE, durable_name)
            await asyncio.sleep(0.5)
            self._cmd_immediate_sub = await self.js.subscribe(
                subject=self.cmd_immediate,
                stream=STREAM_COMMAND_IMMEDIATE,
                durable=durable_name,
                cb=message_handler,
            )
        except NotFoundError:
            logger.error("Stream %s not found even after creation attempt.", STREAM_COMMAND_IMMEDIATE)
            raise

        logger.info(
            "Subscribed to immediate commands: %s (durable: %s, push consumer)",
            self.cmd_immediate, durable_name,
        )

    async def publish_log(self, log_level: str, msg: str, **kwargs) -> None:
        """Publish a log event (core NATS, fire-and-forget)."""
        await self._publish(self.evt_log, {"log_level": log_level, "msg": msg, **kwargs})

    async def publish_alert(self, alert_type: str, severity: str, **kwargs) -> None:
        """Publish an alert event for critical issues."""
        await self._publish(self.evt_alert, {"type": alert_type, "severity": severity, **kwargs})

    async def publish_media(self, media_url: str, media_type: str = "image", **kwargs) -> None:
        """Publish a media event after uploading to object storage."""
        await self._publish(
            self.evt_media,
            {"media_url": media_url, "media_type": media_type, **kwargs},
        )
