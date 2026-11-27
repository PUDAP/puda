"""
Logger service that listens to NATS response streams
and logs command responses to PostgreSQL database.

PUDA Edge Protocol 1.0 observer: it only reads RESPONSE_QUEUE and
RESPONSE_IMMEDIATE through its own durable consumers, never subscribes to
puda.*.cmd.immediate, cmd.ping or update subjects, and never creates,
updates or deletes streams (they belong to the provisioner).
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from nats.aio.msg import Msg
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, RetentionPolicy
from nats.js.errors import NotFoundError
from pydantic import ValidationError
from puda import StreamSubscriber, e2e
from puda.models import NATSMessage
from db_client import DatabaseClient

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Configuration from environment variables
def get_required_env(key: str) -> str:
    """Get required environment variable or raise exception if missing."""
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"Required environment variable '{key}' is not set")
    return value


@dataclass
class NatsConfig:
    """NATS connection settings: plaintext (nats://) or TLS + E2E (tls://)."""
    servers: list[str]
    ca_file: Optional[str] = None
    e2e_key_file: Optional[str] = None

    @property
    def encrypted(self) -> bool:
        return self.e2e_key_file is not None

    @classmethod
    def from_env(cls) -> "NatsConfig":
        """Validate NATS_SERVERS, PUDA_NATS_CA and PUDA_E2E_KEY_FILE.

        Both PUDA_* unset -> plaintext, all servers nats://.
        Both set -> TLS + payload encryption, all servers tls://.
        Anything else is a startup error.
        """
        servers = [s.strip() for s in os.getenv("NATS_SERVERS", "").split(",") if s.strip()]
        if not servers:
            raise ValueError("Required environment variable 'NATS_SERVERS' is not set")
        ca = os.getenv("PUDA_NATS_CA", "").strip()
        key = os.getenv("PUDA_E2E_KEY_FILE", "").strip()
        if bool(ca) != bool(key):
            raise ValueError("Set both PUDA_NATS_CA and PUDA_E2E_KEY_FILE, or neither")
        encrypted = bool(key)
        scheme = "tls://" if encrypted else "nats://"
        if any(not s.startswith(scheme) for s in servers):
            raise ValueError(
                f"{'E2E' if encrypted else 'Plaintext'} mode requires all NATS_SERVERS URLs to use {scheme}"
            )
        if encrypted:
            if not Path(ca).is_file() or not Path(key).is_file():
                raise ValueError("PUDA_NATS_CA and PUDA_E2E_KEY_FILE must reference existing files")
            try:
                e2e.Context(key)
            except Exception:
                raise ValueError("PUDA_E2E_KEY_FILE must contain a valid encrypt key") from None
            if not os.access(key, os.W_OK) or not os.access(Path(key).parent, os.W_OK):
                raise ValueError("Key file and its directory must be writable for key rotation")
            return cls(servers, ca, key)
        return cls(servers)


# NATS stream names
STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"

# Subject patterns to subscribe to (all machines)
NAMESPACE = "puda"
RESPONSE_QUEUE_PATTERN = f"{NAMESPACE}.*.cmd.response.queue"
RESPONSE_IMMEDIATE_PATTERN = f"{NAMESPACE}.*.cmd.response.immediate"

# stream -> (subject, durable consumer, command_type)
SUBSCRIPTIONS = {
    STREAM_RESPONSE_QUEUE: (RESPONSE_QUEUE_PATTERN, "logger_resp_queue", "queue"),
    STREAM_RESPONSE_IMMEDIATE: (RESPONSE_IMMEDIATE_PATTERN, "logger_resp_immediate", "immediate"),
}

KEYRING_POLL_SECONDS = 2
NAK_DELAY_SECONDS = 5


class LoggerService(StreamSubscriber):
    """Service that logs command responses to PostgreSQL."""

    def __init__(self, nats_config: Optional[NatsConfig] = None, db_client: Optional[DatabaseClient] = None):
        self.nats_config = nats_config or NatsConfig.from_env()
        # Initialize StreamSubscriber with NATS servers (TLS CA + E2E key when configured)
        super().__init__(
            servers=self.nats_config.servers,
            ca_file=self.nats_config.ca_file,
            e2e_key_file=self.nats_config.e2e_key_file,
        )

        # Initialize database client
        self.db_client = db_client or DatabaseClient(
            host=get_required_env("POSTGRES_HOST"),
            port=int(get_required_env("POSTGRES_PORT")),
            database=get_required_env("POSTGRES_DB"),
            user=get_required_env("POSTGRES_USER"),
            password=get_required_env("POSTGRES_PASSWORD"),
        )
        self._key_lock = asyncio.Lock()
        self._key_task: Optional[asyncio.Task] = None

    async def connect_db(self):
        """Connect to PostgreSQL database."""
        try:
            self.db_client.connect()
            logger.info("Connected to PostgreSQL database")
        except Exception as e:
            logger.error("Failed to connect to PostgreSQL: %s", e)
            raise

    async def connect(self) -> bool:
        """Connect once; nats-py reconnects (and restores subscriptions) by itself."""
        if self.nc is not None and not self.nc.is_closed:
            self._is_connected = True
            return True
        return await super().connect()

    # ==================== Streams (provisioner-owned) ====================

    async def check_streams(self):
        """Check the provisioned response streams with STREAM.INFO only.

        Never creates, updates or deletes a stream. A missing stream is a startup
        error; a mismatched stream is left unchanged and logged.
        """
        for stream, (subject, _, _) in SUBSCRIPTIONS.items():
            try:
                info = await self.js.stream_info(stream)
            except NotFoundError:
                raise RuntimeError(
                    f"Stream {stream} not found; provision it with infra/nats/jetstream/setup_streams.sh"
                ) from None
            if subject not in (info.config.subjects or []):
                raise RuntimeError(f"Stream {stream} does not include subject {subject}")
            if info.config.retention != RetentionPolicy.INTEREST:
                logger.warning(
                    "Stream %s retention is %s, expected interest; leaving it unchanged",
                    stream, info.config.retention,
                )

    async def subscribe_stream(self, stream: str):
        """Bind (or create) this logger's durable push consumer on a response stream.

        Uses manual acks: the SDK's StreamSubscriber.subscribe auto-acks after the
        callback even when decryption or the database insert failed, and deletes
        the durable when it is "already bound" (dropping interest on an interest
        stream), so it is not used here.
        """
        subject, durable, _ = SUBSCRIPTIONS[stream]
        try:
            info = await self.js.consumer_info(stream, durable)
        except NotFoundError:
            info = None
        if info is not None:
            cfg = info.config
            if (cfg.filter_subject or subject) != subject or cfg.ack_policy != AckPolicy.EXPLICIT \
                    or not cfg.deliver_subject:
                raise RuntimeError(
                    f"Incompatible existing consumer {durable} on {stream}; remove it with "
                    f"'nats consumer rm {stream} {durable}'"
                )
            config = None
        else:
            config = ConsumerConfig(
                durable_name=durable,
                filter_subject=subject,
                ack_policy=AckPolicy.EXPLICIT,
                deliver_policy=DeliverPolicy.ALL,
                ack_wait=60,
            )

        async def callback(msg: Msg):
            await self.handle_message(msg, stream, subject)

        sub = await self.js.subscribe(
            subject, stream=stream, durable=durable, config=config,
            cb=callback, manual_ack=True,
        )
        self._subscriptions.append(sub)
        logger.info("Subscribed to stream=%s, subject=%s, durable=%s", stream, subject, durable)

    # ==================== E2E keyring ====================

    async def sync_keyring(self):
        """Adopt the rotation record in KV E2E_KEYRING/current (no-op in plaintext mode)."""
        if not self.encryption.enabled():
            return
        async with self._key_lock:
            try:
                kv = await self.js.key_value(e2e.KEYRING_BUCKET)
            except NotFoundError:
                return
            try:
                entry = await kv.get(e2e.KEYRING_KEY)
            except NotFoundError:
                self.encryption.drop_previous()
                return
            plain = self.encryption.open_payload(
                e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), entry.value
            )
            if self.encryption.adopt_record(plain):
                logger.info("Adopted E2E keyring rotation")

    async def _watch_keys(self):
        while True:
            await asyncio.sleep(KEYRING_POLL_SECONDS)
            try:
                await self.sync_keyring()
            except Exception as exc:
                logger.error("Keyring refresh failed (%s); retaining current keys", type(exc).__name__)

    async def open_payload(self, msg: Msg) -> bytes:
        """Open a payload; plaintext is refused when keyed and frames when unkeyed."""
        try:
            return self.encryption.open_payload(msg.subject, msg.data)
        except e2e.E2EError:
            if not self.encryption.enabled():
                raise
            # A newly rotated message may arrive before the periodic keyring refresh.
            await self.sync_keyring()
            return self.encryption.open_payload(msg.subject, msg.data)

    # ==================== Messages ====================

    async def handle_message(self, msg: Msg, stream: str, subject: str):
        """
        Handle an incoming message from any subscribed stream.

        Determines command_type from stream name and stores the response.
        Ack on success, nak (redeliver) on decrypt/database failure,
        term on an invalid envelope.
        """
        command_type = SUBSCRIPTIONS.get(stream, (None, None, None))[2]
        if command_type is None:
            logger.error("Unknown stream: %s", stream)
            await msg.term()
            return
        try:
            payload = await self.open_payload(msg)
        except Exception as exc:
            logger.error("Cannot decrypt message on %s (%s)", msg.subject, type(exc).__name__)
            await msg.nak(delay=NAK_DELAY_SECONDS)
            return
        # Parse bytes to NATSMessage object (rejects missing/unsupported header.protocol_version)
        try:
            nats_message = NATSMessage.model_validate_json(payload)
        except (ValidationError, ValueError) as e:
            logger.error("Invalid message on %s: %s", msg.subject, e)
            await msg.term()
            return
        try:
            self.db_client.insert_command_log(message=nats_message, command_type=command_type)
        except Exception:
            logger.exception("Database insert failed; message will be redelivered")
            await msg.nak(delay=NAK_DELAY_SECONDS)
            return
        await msg.ack()

    async def on_start(self):
        """Check streams, load keys and set up durable subscriptions."""
        await self.check_streams()
        await self.sync_keyring()
        if self.encryption.enabled():
            self._key_task = asyncio.create_task(self._watch_keys())
        for stream in SUBSCRIPTIONS:
            await self.subscribe_stream(stream)
        logger.info("Logger ready (%s)", "E2EE" if self.encryption.enabled() else "plaintext")

    async def _resubscribe_all(self):
        """No-op: nats-py restores push subscriptions on reconnect and the durables
        keep their position server-side. Re-subscribing would hit "already bound"."""

    async def disconnect(self):
        """Disconnect from NATS and close database connection."""
        # Call parent disconnect to handle NATS cleanup
        await super().disconnect()

        # Close database connection
        self.db_client.close()
        logger.info("Disconnected from NATS and PostgreSQL")

    async def on_stop(self):
        """Cleanup when the service stops."""
        # Database cleanup is handled in disconnect()
        if self._key_task is not None:
            self._key_task.cancel()
            self._key_task = None

    async def run(self, health_check_interval: float = 1.0):
        """
        Run the logger service.

        Args:
            health_check_interval: Interval in seconds to check connection health
        """
        # Connect to database first
        await self.connect_db()

        # Use parent's run() method which handles NATS connection and health monitoring
        await super().run(health_check_interval=health_check_interval)


async def main():
    """Main entry point."""
    service = LoggerService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
