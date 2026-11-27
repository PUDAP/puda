"""
Reusable NATS JetStream subscriber for services that need to consume messages.

Provides a base class for subscribing to NATS streams with durable consumers,
automatic reconnection, and message handling callbacks.

This implements a push consumer pattern where NATS JetStream automatically
delivers messages to registered callbacks as they arrive, rather than requiring
the client to explicitly fetch/pull messages.
"""
import asyncio
import logging
from typing import Optional, Callable, Awaitable, List, Any
from abc import abstractmethod
import nats
from nats.errors import TimeoutError as NATSTimeoutError
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError
from nats.aio.msg import Msg

from . import e2e

logger = logging.getLogger(__name__)


class StreamSubscriber:
    """
    Base class for subscribing to NATS JetStream streams using push consumer pattern.
    
    This class implements a push consumer where NATS JetStream automatically delivers
    messages to registered callbacks as they arrive. The server pushes messages to
    the client rather than requiring the client to pull/fetch them.
    
    Handles connection management, durable subscriptions, and message routing.
    Services can extend this class and implement message handling logic.

    Acknowledgement is the handler's job (``manual_ack``): call ``msg.ack()`` once
    the message is stored, ``msg.term()`` for one that can never succeed. A
    message whose payload cannot be opened, or whose handler raises, is
    negatively acknowledged with a delay so JetStream redelivers it; it is never
    acked on failure. Messages of one subscription are handled one at a time.

    Subscriptions survive reconnects: nats-py restores them itself, so nothing is
    re-subscribed. With a payload key, the subscriber follows key rotation in
    ``E2E_KEYRING/current``. It never creates, updates or deletes streams,
    consumers' streams or KV buckets.
    
    Example:
        ```python
        class MyService(StreamSubscriber):
            async def handle_message(self, msg: Msg, stream: str, subject: str):
                # Process message
                data = json.loads(msg.data.decode())
                # ... your logic ...
                await msg.ack()
        
        service = MyService(servers=["nats://localhost:4222"])
        await service.subscribe("STREAM_NAME", "puda.*.cmd.response.queue", "my_consumer")
        await service.run()
        ```
    """
    
    def __init__(
        self,
        servers: List[str],
        connect_timeout: int = 10,
        reconnect_time_wait: int = 2,
        max_reconnect_attempts: int = -1,
        *,
        ca_file: str | None = None,
        e2e_key_file: str | None = None,
    ):
        """
        Initialize the stream subscriber.
        
        Args:
            servers: List of NATS server URLs (e.g., ["nats://localhost:4222"])
            connect_timeout: Timeout for initial connection in seconds
            reconnect_time_wait: Wait time between reconnection attempts in seconds
            max_reconnect_attempts: Maximum reconnection attempts (-1 for unlimited)
            ca_file: Explicit CA certificate path for tls:// connections.
            e2e_key_file: Optional payload key file; no environment lookup.
        """
        if not servers:
            raise ValueError("servers must be a non-empty list")
        
        self.servers = servers
        self._connect_kwargs = e2e.connect_kwargs(servers, ca_file)
        self.encryption = e2e.Context(e2e_key_file)
        self.connect_timeout = connect_timeout
        self.reconnect_time_wait = reconnect_time_wait
        self.max_reconnect_attempts = max_reconnect_attempts
        
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self._subscriptions: List[Any] = []
        self._is_connected = False
        self._should_run = True
        self._keyring_task: Optional[asyncio.Task] = None
        # Delay before JetStream redelivers a message that failed.
        self.nak_delay: float = 5.0
    
    async def connect(self) -> bool:
        """
        Connect to NATS servers.
        
        Returns:
            True if connected successfully, False otherwise
        """
        if self.nc is not None and not self.nc.is_closed:
            # Connected, or nats-py is reconnecting this connection; never open a second one.
            return True
        
        try:
            self.nc = await nats.connect(
                servers=self.servers,
                connect_timeout=self.connect_timeout,
                reconnect_time_wait=self.reconnect_time_wait,
                max_reconnect_attempts=self.max_reconnect_attempts,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback,
                **self._connect_kwargs,
            )
            self.js = self.nc.jetstream()
            self._is_connected = True
            self._start_keyring_watch()
            logger.info("Connected to NATS servers: %s", self.servers)
            return True
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", e)
            self._is_connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from NATS and cleanup subscriptions."""
        self._should_run = False
        self._stop_keyring_watch()
        
        # Unsubscribe from all streams
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception as e:
                logger.debug("Error unsubscribing: %s", e)
        self._subscriptions.clear()
        
        # Close NATS connection
        if self.nc:
            await self.nc.close()
            self.nc = None
            self.js = None
        
        self._is_connected = False
        logger.info("Disconnected from NATS")
    
    async def subscribe(
        self,
        stream: str,
        subject: str,
        durable: Optional[str] = None,
        callback: Optional[Callable[[Msg, str, str], Awaitable[None]]] = None
    ):
        """
        Subscribe to a NATS JetStream stream using push consumer pattern.
        
        This creates a push subscription where NATS JetStream automatically delivers
        messages to the callback as they arrive. Messages are pushed to the client
        rather than requiring explicit fetch/pull operations.
        
        Args:
            stream: Name of the JetStream stream
            subject: Subject pattern to subscribe to (supports wildcards)
            durable: Optional durable consumer name (for persistent subscriptions)
            callback: Optional async callback function(msg, stream, subject) -> None
                     If not provided, calls handle_message() method
        
        Raises:
            RuntimeError: If not connected to NATS
        """
        if not self._is_connected or not self.js:
            raise RuntimeError("Not connected to NATS. Call connect() first.")
        
        # Use provided callback or default to handle_message method
        if callback is None:
            callback = self.handle_message
        
        async def message_wrapper(msg: Msg):
            try:
                msg.data = self.encryption.open_payload(msg.subject, msg.data)
            except e2e.E2EError as exc:
                # Possibly a key we have not adopted yet: refresh, then redeliver.
                logger.error("Cannot open payload on %s: %s", msg.subject, exc)
                await self._refresh_keyring()
                await self._nak(msg)
                return
            try:
                await callback(msg, stream, subject)
            except Exception:
                logger.exception(
                    "Error in message callback for stream=%s, subject=%s", stream, subject
                )
                await self._nak(msg)

        kwargs: dict[str, Any] = {"stream": stream, "cb": message_wrapper, "manual_ack": True}
        if durable:
            kwargs["durable"] = durable
        try:
            sub = await self.js.subscribe(subject, **kwargs)
        except Exception as e:
            if durable and "already bound" in str(e).lower():
                # Deleting the durable would drop its pending messages (interest
                # retention keeps them only for existing consumers), so never do it.
                raise RuntimeError(
                    f"Consumer '{durable}' on stream '{stream}' is already bound to another "
                    "subscriber, probably another instance of this service. Stop it, or use "
                    "a different durable name; if no instance is running, wait for the old "
                    f"connection to time out. Last resort: nats consumer rm {stream} {durable} "
                    "(drops its pending messages)."
                ) from e
            logger.error("Failed to subscribe to stream=%s, subject=%s: %s", stream, subject, e)
            raise
        self._subscriptions.append(sub)
        logger.info(
            "Subscribed to stream=%s, subject=%s, durable=%s",
            stream, subject, durable or "ephemeral"
        )

    async def _nak(self, msg: Msg) -> None:
        try:
            await msg.nak(delay=self.nak_delay)
        except Exception as exc:
            # Already acked/terminated by the handler, or the connection is down;
            # JetStream redelivers after ack_wait in the latter case.
            logger.debug("Could not nak message on %s: %s", msg.subject, exc)

    @abstractmethod
    async def handle_message(self, msg: Msg, stream: str, subject: str):
        """
        Handle an incoming message pushed by NATS JetStream. Override this method in subclasses.
        
        This method is called automatically when NATS JetStream pushes a message
        to this subscriber. The push consumer pattern means messages arrive
        asynchronously via callbacks rather than being explicitly fetched.
        
        Default implementation logs and acks the message.
        Subclasses should implement their own message processing logic.
        
        Args:
            msg: NATS message object
            stream: Name of the stream the message came from
            subject: Subject pattern that matched this message
        """
        logger.debug(
            "Received message from stream=%s, subject=%s, data_size=%d",
            stream, subject, len(msg.data)
        )
        # Default: ack the message
        await msg.ack()
    
    async def _error_callback(self, error: Exception):
        """Callback for NATS errors."""
        if error:
            logger.error("NATS error: %s", error, exc_info=True)
        else:
            logger.error("NATS error: Unknown error (error object is None)")
    
    async def _disconnected_callback(self):
        """Callback when disconnected from NATS."""
        logger.warning("Disconnected from NATS servers")
        self._is_connected = False
    
    async def _reconnected_callback(self):
        """Callback when reconnected to NATS.

        nats-py restores every subscription on the same connection, so this only
        refreshes state; re-subscribing would create duplicate subscriptions.
        """
        logger.info("Reconnected to NATS servers")
        self._is_connected = True
        self._start_keyring_watch()
    
    async def _closed_callback(self):
        """Callback when connection is closed."""
        logger.info("NATS connection closed")
        self._is_connected = False

    # ==================== Key rotation ====================

    def _start_keyring_watch(self) -> None:
        self._stop_keyring_watch()
        if self.encryption.enabled() and self.js is not None:
            self._keyring_task = asyncio.get_running_loop().create_task(self._watch_keyring())

    def _stop_keyring_watch(self) -> None:
        if self._keyring_task is not None:
            self._keyring_task.cancel()
            self._keyring_task = None

    async def _watch_keyring(self) -> None:
        """Follow ``E2E_KEYRING/current`` (Edge Protocol 1.0, section 13.5)."""
        try:
            kv = await self.js.key_value(e2e.KEYRING_BUCKET)
            await self._refresh_keyring(kv)
            watcher = await kv.watch(e2e.KEYRING_KEY)
            while True:
                try:
                    entry = await watcher.updates(timeout=30)
                except (asyncio.TimeoutError, NATSTimeoutError):
                    continue
                if entry is None:
                    continue
                if getattr(entry, "operation", None) in ("DEL", "PURGE"):
                    self.encryption.drop_previous()
                    continue
                self._apply_keyring_value(entry.value)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Keyring watch stopped: %s", exc)

    async def _refresh_keyring(self, kv: Any = None) -> None:
        if not self.encryption.enabled() or self.js is None:
            return
        try:
            kv = kv or await self.js.key_value(e2e.KEYRING_BUCKET)
            entry = await kv.get(e2e.KEYRING_KEY)
        except NotFoundError:
            self.encryption.drop_previous()
            return
        except Exception as exc:
            logger.warning("Cannot read %s/%s: %s", e2e.KEYRING_BUCKET, e2e.KEYRING_KEY, exc)
            return
        self._apply_keyring_value(getattr(entry, "value", None))

    def _apply_keyring_value(self, value: bytes | None) -> None:
        if value is None:
            self.encryption.drop_previous()
            return
        try:
            plain = self.encryption.open_payload(
                e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), value
            )
            if self.encryption.adopt_record(plain):
                logger.info("Adopted rotated E2E keyring")
        except e2e.E2EError as exc:
            logger.error("Failed to adopt keyring: %s", exc)
    
    async def run(self, health_check_interval: float = 1.0):
        """
        Run the subscriber service.
        
        This method will:
        1. Connect to NATS (with retry logic)
        2. Call on_start() hook for subclasses to set up subscriptions
        3. Wait while nats-py keeps the connection (and its subscriptions) alive.
           Only if the connection closes for good (reconnect attempts exhausted)
           does it connect again and call on_start() again.
        4. Call on_stop() hook on shutdown
        
        Args:
            health_check_interval: Interval in seconds to check the connection
        """
        async def connect_and_start() -> None:
            while self._should_run:
                if await self.connect():
                    break
                logger.warning("Failed to connect to NATS, retrying in 5 seconds...")
                await asyncio.sleep(5)
            if self._should_run:
                self._subscriptions.clear()
                await self.on_start()

        try:
            await connect_and_start()
            logger.info("Stream subscriber service started")
            while self._should_run:
                await asyncio.sleep(health_check_interval)
                if self.nc is not None and self.nc.is_closed:
                    logger.warning("NATS connection closed; connecting again")
                    self.nc = None
                    self.js = None
                    await connect_and_start()
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt, shutting down...")
        except Exception as e:
            logger.error("Unexpected error in main loop: %s", e, exc_info=True)
        finally:
            await self.on_stop()
            await self.disconnect()
    
    @abstractmethod
    async def on_start(self):
        """
        Hook called when the service starts. Override in subclasses to set up subscriptions.
        
        Example:
            ```python
            async def on_start(self):
                await self.subscribe("STREAM_NAME", "puda.*.cmd.response.queue", "my_consumer")
                await self.subscribe("STREAM_NAME", "puda.*.cmd.response.immediate", "my_consumer2")
            ```
        """
        pass
    
    @abstractmethod
    async def on_stop(self):
        """
        Hook called when the service stops. Override in subclasses for cleanup.
        """
        pass
    
    # ==================== Context Manager ====================
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False  # Don't suppress exceptions
