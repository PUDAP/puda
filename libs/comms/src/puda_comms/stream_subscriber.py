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
from nats.js.client import JetStreamContext
from nats.aio.msg import Msg

logger = logging.getLogger(__name__)


class StreamSubscriber:
    """
    Base class for subscribing to NATS JetStream streams using push consumer pattern.
    
    This class implements a push consumer where NATS JetStream automatically delivers
    messages to registered callbacks as they arrive. The server pushes messages to
    the client rather than requiring the client to pull/fetch them.
    
    Handles connection management, durable subscriptions, and message routing.
    Services can extend this class and implement message handling logic.
    
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
        max_reconnect_attempts: int = -1
    ):
        """
        Initialize the stream subscriber.
        
        Args:
            servers: List of NATS server URLs (e.g., ["nats://localhost:4222"])
            connect_timeout: Timeout for initial connection in seconds
            reconnect_time_wait: Wait time between reconnection attempts in seconds
            max_reconnect_attempts: Maximum reconnection attempts (-1 for unlimited)
        """
        if not servers:
            raise ValueError("servers must be a non-empty list")
        
        self.servers = servers
        self.connect_timeout = connect_timeout
        self.reconnect_time_wait = reconnect_time_wait
        self.max_reconnect_attempts = max_reconnect_attempts
        
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self._subscriptions: List[Any] = []
        self._is_connected = False
        self._should_run = True
    
    async def connect(self) -> bool:
        """
        Connect to NATS servers.
        
        Returns:
            True if connected successfully, False otherwise
        """
        if self._is_connected:
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
                closed_cb=self._closed_callback
            )
            self.js = self.nc.jetstream()
            self._is_connected = True
            logger.info("Connected to NATS servers: %s", self.servers)
            return True
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", e)
            self._is_connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from NATS and cleanup subscriptions."""
        self._should_run = False
        
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
        
        # Create callback wrapper
        async def message_wrapper(msg: Msg):
            try:
                await callback(msg, stream, subject)
            except Exception as e:
                logger.error(
                    "Error in message callback for stream=%s, subject=%s: %s",
                    stream, subject, e, exc_info=True
                )
                # Don't ack on error - let the caller decide
                # This allows for retry logic in the handler
        
        try:
            # Subscribe with durable consumer if specified
            if durable:
                sub = await self.js.subscribe(
                    subject,
                    stream=stream,
                    durable=durable,
                    cb=lambda msg: asyncio.create_task(message_wrapper(msg))
                )
            else:
                # Ephemeral subscription
                sub = await self.js.subscribe(
                    subject,
                    stream=stream,
                    cb=lambda msg: asyncio.create_task(message_wrapper(msg))
                )
            
            self._subscriptions.append(sub)
            logger.info(
                "Subscribed to stream=%s, subject=%s, durable=%s",
                stream, subject, durable or "ephemeral"
            )
        except Exception as e:
            error_msg = str(e)
            # Handle the specific case where consumer is already bound
            if "consumer is already bound" in error_msg.lower():
                logger.warning(
                    "Consumer '%s' for stream '%s' is already bound. "
                    "This usually happens when the service didn't shut down cleanly. "
                    "Attempting to delete the consumer and retry...",
                    durable, stream
                )
                if durable:
                    try:
                        # Try to delete the consumer (may fail if actively bound)
                        await self.js.delete_consumer(stream, durable)
                        logger.info("Deleted consumer '%s' for stream '%s'", durable, stream)
                        # Retry subscription after deletion
                        sub = await self.js.subscribe(
                            subject,
                            stream=stream,
                            durable=durable,
                            cb=lambda msg: asyncio.create_task(message_wrapper(msg))
                        )
                        self._subscriptions.append(sub)
                        logger.info(
                            "Successfully subscribed after consumer cleanup: stream=%s, subject=%s, durable=%s",
                            stream, subject, durable
                        )
                    except Exception as retry_error:
                        retry_error_msg = str(retry_error)
                        if "bound" in retry_error_msg.lower() or "in use" in retry_error_msg.lower():
                            logger.error(
                                "Consumer '%s' for stream '%s' cannot be deleted because it's still bound. "
                                "This typically means the previous service instance is still running or "
                                "the subscription hasn't timed out yet. Solutions:\n"
                                "  1. Wait a few seconds and restart the service\n"
                                "  2. Manually delete the consumer: nats consumer rm %s %s\n"
                                "  3. Restart the NATS server\n"
                                "  4. Use a different durable consumer name",
                                durable, stream, stream, durable
                            )
                        else:
                            logger.error(
                                "Failed to delete consumer '%s' for stream '%s': %s",
                                durable, stream, retry_error
                            )
                        raise
                else:
                    raise
            else:
                logger.error(
                    "Failed to subscribe to stream=%s, subject=%s: %s",
                    stream, subject, e
                )
                raise
    
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
        """Callback when reconnected to NATS."""
        logger.info("Reconnected to NATS servers")
        self._is_connected = True
        if self.nc:
            self.js = self.nc.jetstream()
            # Clear old subscriptions as they're no longer valid after reconnection
            self._subscriptions.clear()
            # Re-subscribe to all streams
            await self._resubscribe_all()
    
    async def _closed_callback(self):
        """Callback when connection is closed."""
        logger.info("NATS connection closed")
        self._is_connected = False
    
    async def _resubscribe_all(self):
        """
        Re-subscribe to all streams after reconnection.
        
        Override this method in subclasses to restore subscriptions.
        The default implementation does nothing - subclasses should track
        their subscriptions and re-subscribe here.
        """
        logger.debug("Reconnection detected, but no subscriptions to restore")
    
    async def run(self, health_check_interval: float = 1.0):
        """
        Run the subscriber service with connection health monitoring.
        
        This method will:
        1. Connect to NATS (with retry logic)
        2. Call on_start() hook for subclasses to set up subscriptions
        3. Monitor connection health and reconnect if needed
        4. Call on_stop() hook on shutdown
        
        Args:
            health_check_interval: Interval in seconds to check connection health
        """
        # Connect to NATS with retry logic
        while self._should_run:
            if await self.connect():
                break
            logger.warning("Failed to connect to NATS, retrying in 5 seconds...")
            await asyncio.sleep(5)
        
        # Call on_start hook for subclasses to set up subscriptions
        await self.on_start()
        
        logger.info("Stream subscriber service started")
        
        # Main loop with health monitoring
        try:
            while self._should_run:
                await asyncio.sleep(health_check_interval)
                
                # Check connection health
                if not self._is_connected:
                    logger.warning("Connection lost, attempting to reconnect...")
                    if await self.connect():
                        # Clear old subscriptions as they're no longer valid after reconnection
                        self._subscriptions.clear()
                        await self._resubscribe_all()
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

