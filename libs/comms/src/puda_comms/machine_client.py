"""
Basic default NATS Client for Generic Machines
Handles commands, telemetry, and events following the puda.{machine_id}.{category}.{sub_category} pattern
"""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from typing import Dict, Any, Optional, Callable, Tuple, Awaitable
from datetime import datetime, timezone
import nats
from puda_comms.types import CommandResponseStatus
from nats.js.client import JetStreamContext
from nats.js.api import StreamConfig
from nats.js.errors import NotFoundError
from nats.aio.msg import Msg

logger = logging.getLogger(__name__)


class MachineClient:
    """
    NATS client for machines.
    
    Subject pattern: puda.{machine_id}.{category}.{sub_category}
    - Telemetry: core NATS (no JetStream)
    - Commands: JetStream with exactly-once delivery
      - Queue commands: COMMAND_QUEUE stream (WorkQueue retention)
      - Immediate commands: COMMAND_IMMEDIATE stream (WorkQueue retention)
    - Command responses: JetStream streams (Interest retention)
      - Queue responses: RESPONSE_QUEUE stream (Interest retention)
      - Immediate responses: RESPONSE_IMMEDIATE stream (Interest retention)
    - Events: Core NATS (fire-and-forget, no JetStream)
    """
    
    # Constants
    NAMESPACE = "puda"
    KEEP_ALIVE_INTERVAL = 25  # seconds
    STREAM_COMMAND_QUEUE = "COMMAND_QUEUE"
    STREAM_COMMAND_IMMEDIATE = "COMMAND_IMMEDIATE"
    STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
    STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"
    
    def __init__(self, servers: list[str], machine_id: str):
        """
        Initialize NATS client for machine.
        
        Args:
            servers: List of NATS server URLs (e.g., ["nats://localhost:4222"])
            machine_id: Machine identifier (e.g., "opentron")
        """
        self.servers = servers
        self.machine_id = machine_id
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self.kv = None
        
        # Generate subject and stream names
        self._init_subjects()
        
        # Default subscriptions
        self._cmd_queue_sub = None
        self._cmd_immediate_sub = None
        
        # Connection state
        self._is_connected = False
        self._reconnect_handlers = []
        
        # Queue control state
        self._pause_lock = asyncio.Lock()
        self._is_paused = False
        self._cancelled_run_ids = set()
    
    def _init_subjects(self):
        """Initialize all subject and stream names."""
        namespace = self.NAMESPACE
        machine_id_safe = self.machine_id.replace('.', '-')
        
        # Telemetry subjects (core NATS, no JetStream)
        self.tlm_heartbeat = f"{namespace}.{machine_id_safe}.tlm.heartbeat"
        self.tlm_pos = f"{namespace}.{machine_id_safe}.tlm.pos"
        self.tlm_health = f"{namespace}.{machine_id_safe}.tlm.health"
        
        # Command subjects (JetStream, exactly-once)
        self.cmd_queue = f"{namespace}.{machine_id_safe}.cmd.queue"
        self.cmd_immediate = f"{namespace}.{machine_id_safe}.cmd.immediate"
        
        # Response subjects (JetStream streams)
        self.response_queue = f"{namespace}.{machine_id_safe}.cmd.response.queue"
        self.response_immediate = f"{namespace}.{machine_id_safe}.cmd.response.immediate"
        
        # Event subjects (Core NATS, no JetStream)
        self.evt_log = f"{namespace}.{machine_id_safe}.evt.log"
        self.evt_alert = f"{namespace}.{machine_id_safe}.evt.alert"
        self.evt_media = f"{namespace}.{machine_id_safe}.evt.media"
        
        # KV bucket name for status
        self.kv_bucket_name = f"MACHINE_STATE_{machine_id_safe}"
    
    # ==================== HELPER METHODS ====================
    
    @staticmethod
    def _format_timestamp() -> str:
        """Format current timestamp as ISO 8601 UTC string."""
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    def _parse_message(self, data: bytes) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
        """
        Parse message payload and extract header information.
        
        Returns:
            Tuple of (payload, run_id, command_id)
        """
        payload = json.loads(data.decode())
        header = payload.get('header', {})
        run_id = header.get('run_id')
        command_id = header.get('command_id', 'unknown')
        return payload, run_id, command_id
    
    async def _publish_telemetry(self, subject: str, data: Dict[str, Any]) -> bool:
        """Publish telemetry message to core NATS."""
        if not self.nc:
            logger.warning("NATS not connected, skipping %s", subject)
            return False
        
        try:
            message = {'timestamp': self._format_timestamp(), **data}
            await self.nc.publish(subject, json.dumps(message).encode())
            logger.debug("Published to %s", subject)
            return True
        except Exception as e:
            logger.error("Error publishing to %s: %s", subject, e)
            return False
    
    async def _publish_event(self, subject: str, data: Dict[str, Any]) -> bool:
        """Publish event message to Core NATS (fire-and-forget)."""
        if not self.nc:
            logger.warning("NATS not connected, skipping %s", subject)
            return False
        
        try:
            message = {'timestamp': self._format_timestamp(), **data}
            await self.nc.publish(subject, json.dumps(message).encode())
            logger.debug("Published to %s", subject)
            return True
        except Exception as e:
            logger.error("Error publishing to %s: %s", subject, e)
            return False
    
    async def _ensure_stream(self, stream_name: str, subject_pattern: str, retention: str = 'workqueue'):
        """
        Ensure a stream exists with the specified retention policy.
        
        Args:
            stream_name: Name of the stream (e.g., STREAM_COMMAND_QUEUE)
            subject_pattern: Subject pattern for the stream (e.g., "puda.*.cmd.queue")
            retention: Retention policy ('workqueue', 'interest', or 'limits'). Defaults to 'workqueue'
        """
        if not self.js:
            return
        
        try:
            # Try to get existing stream
            stream_info = await self.js.stream_info(stream_name)
            # Check if it has the correct pattern and retention
            config = stream_info.config
            if subject_pattern not in config.subjects or getattr(config, 'retention', None) != retention:
                logger.info("Updating %s stream: subject=%s, retention=%s", stream_name, subject_pattern, retention)
                updated_config = StreamConfig(
                    name=stream_name,
                    subjects=[subject_pattern],
                    retention=retention
                )
                await self.js.update_stream(updated_config)
                logger.info("Successfully updated %s stream", stream_name)
        except NotFoundError:
            # Stream doesn't exist, create it
            logger.info("Creating %s stream: subject=%s, retention=%s", stream_name, subject_pattern, retention)
            await self.js.add_stream(
                StreamConfig(
                    name=stream_name,
                    subjects=[subject_pattern],
                    retention=retention
                )
            )
            logger.info("Successfully created %s stream", stream_name)
        except Exception as e:
            logger.error("Error ensuring %s stream: %s", stream_name, e, exc_info=True)
            raise
    
    async def _ensure_command_queue_stream(self):
        """Ensure COMMAND_QUEUE stream exists with WorkQueue retention policy."""
        await self._ensure_stream(
            self.STREAM_COMMAND_QUEUE,
            f"{self.NAMESPACE}.*.cmd.queue"
        )
    
    async def _ensure_command_immediate_stream(self):
        """Ensure COMMAND_IMMEDIATE stream exists with WorkQueue retention policy."""
        await self._ensure_stream(
            self.STREAM_COMMAND_IMMEDIATE,
            f"{self.NAMESPACE}.*.cmd.immediate"
        )
    
    async def _ensure_response_queue_stream(self):
        """Ensure RESPONSE_QUEUE stream exists with Interest retention policy."""
        await self._ensure_stream(
            self.STREAM_RESPONSE_QUEUE,
            f"{self.NAMESPACE}.*.cmd.response.queue",
            retention='interest'
        )
    
    async def _ensure_response_immediate_stream(self):
        """Ensure RESPONSE_IMMEDIATE stream exists with Interest retention policy."""
        await self._ensure_stream(
            self.STREAM_RESPONSE_IMMEDIATE,
            f"{self.NAMESPACE}.*.cmd.response.immediate",
            retention='interest'
        )
    
    async def _get_or_create_kv_bucket(self):
        """Get or create KV bucket, handling errors gracefully."""
        if not self.js:
            return None
        
        try:
            return await self.js.create_key_value(bucket=self.kv_bucket_name)
        except Exception:
            try:
                return await self.js.key_value(self.kv_bucket_name)
            except Exception as e:
                logger.warning("Could not create or access KV bucket: %s", e)
                return None
    
    async def _cleanup_subscriptions(self):
        """Unsubscribe from all subscriptions."""
        # Clean up subscriptions
        if self._cmd_queue_sub:
            try:
                await self._cmd_queue_sub.unsubscribe()
            except Exception:
                pass
            self._cmd_queue_sub = None
        
        if self._cmd_immediate_sub:
            try:
                await self._cmd_immediate_sub.unsubscribe()
            except Exception:
                pass
            self._cmd_immediate_sub = None
    
    def _reset_connection_state(self):
        """Reset connection-related state."""
        self._is_connected = False
        self.js = None
        self.kv = None
        # Subscriptions will be recreated on reconnection
        self._cmd_queue_sub = None
        self._cmd_immediate_sub = None
    
    # ==================== CONNECTION MANAGEMENT ====================
    
    async def connect(self) -> bool:
        """Connect to NATS server and initialize JetStream with auto-reconnection."""
        try:
            self.nc = await nats.connect(
                servers=self.servers,
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback
            )
            self.js = self.nc.jetstream()
            await self._ensure_command_queue_stream()
            await self._ensure_command_immediate_stream()
            await self._ensure_response_queue_stream()
            await self._ensure_response_immediate_stream()
            self.kv = await self._get_or_create_kv_bucket()
            self._is_connected = True
            logger.info("Connected to NATS servers: %s", self.servers)
            return True
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", e)
            self._reset_connection_state()
            return False
    
    async def _error_callback(self, error: Exception):
        """Callback for NATS errors."""
        logger.error("NATS error: %s", error)
    
    async def _disconnected_callback(self):
        """Callback when disconnected from NATS."""
        logger.warning("Disconnected from NATS servers")
        self._reset_connection_state()
    
    async def _reconnected_callback(self):
        """Callback when reconnected to NATS."""
        logger.info("Reconnected to NATS servers")
        self._is_connected = True
        
        if self.nc:
            self.js = self.nc.jetstream()
            await self._ensure_command_queue_stream()
            await self._ensure_command_immediate_stream()
            await self._ensure_response_queue_stream()
            await self._ensure_response_immediate_stream()
            self.kv = await self._get_or_create_kv_bucket()
            await self._resubscribe_handlers()
    
    async def _resubscribe_handlers(self):
        """Re-subscribe to all handlers after reconnection."""
        subscribe_methods = {
            'queue': self.subscribe_queue,
            'immediate': self.subscribe_immediate,
        }
        
        for handler_info in self._reconnect_handlers:
            try:
                handler_type = handler_info['type']
                handler = handler_info['handler']
                subscribe_method = subscribe_methods.get(handler_type)
                
                if subscribe_method:
                    await subscribe_method(handler)
                else:
                    logger.warning("Unknown handler type: %s", handler_type)
            except Exception as e:
                logger.error("Failed to re-subscribe %s: %s", handler_type, e)
    
    async def _closed_callback(self):
        """Callback when connection is closed."""
        logger.info("NATS connection closed")
        self._reset_connection_state()
    
    async def disconnect(self):
        """Disconnect from NATS server."""
        await self._cleanup_subscriptions()
        if self.nc:
            await self.nc.close()
            self._reset_connection_state()
            logger.info("Disconnected from NATS")
    
    # ==================== TELEMETRY (Core NATS, no JetStream) ====================
    
    async def publish_heartbeat(self):
        """Publish heartbeat telemetry (timestamp only)."""
        await self._publish_telemetry(self.tlm_heartbeat, {})
    
    async def publish_position(self, coords: Dict[str, float]):
        """Publish real-time position coordinates."""
        await self._publish_telemetry(self.tlm_pos, coords)
    
    async def publish_health(self, vitals: Dict[str, Any]):
        """Publish system health vitals (CPU, memory, temperature, etc.)."""
        await self._publish_telemetry(self.tlm_health, vitals)
    
    async def publish_state(self, data: Dict[str, Any]):
        """
        Overwrites machine state in nats KV store.
        
        Args:
            status_data: Dictionary with state data
        """
        if not self.kv:
            logger.warning("KV store not available, skipping state update")
            return
        
        try:
            message = {'timestamp': self._format_timestamp(), **data}
            await self.kv.put(self.machine_id, json.dumps(message).encode())
            logger.info("Updated state in KV store: %s", message)
        except Exception as e:
            logger.error("Error updating status in KV store: %s", e)
            
    # ==================== COMMANDS (JetStream, exactly-once with run_id) ====================
    
    
    @asynccontextmanager
    async def _keep_message_alive(self, msg: Msg, interval: int = KEEP_ALIVE_INTERVAL):
        """
        Context manager that maintains a background task to reset the 
        redelivery timer (in_progress) while the block/machine is executing.
        """
        async def _heartbeat():
            while True:
                await asyncio.sleep(interval)
                try:
                    await msg.in_progress()
                    logger.debug("Reset redelivery timer via keep-alive")
                except Exception:
                    break

        task = asyncio.create_task(_heartbeat())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    async def _publish_command_response(
        self,
        msg: Msg,
        status: CommandResponseStatus,
        error: Optional[str] = None,
        response_stream: str = None
    ):
        """
        Publish command response message to JetStream response stream.
        
        Args:
            msg: NATS message
            status: Status of the command (success, error)
            error: Error message if status is error
            response_stream: Which response stream to use (STREAM_RESPONSE_QUEUE or STREAM_RESPONSE_IMMEDIATE)
        """
        if not self.js:
            return
        
        if response_stream is None:
            response_stream = self.STREAM_RESPONSE_QUEUE
        
        try:
            payload, run_id, command_id = self._parse_message(msg.data)
            if not run_id:
                return
            
            # Append response to the original payload
            payload['result'] = {
                'status': status,
                'completed_at': self._format_timestamp(),
            }
            
            if error:
                payload['result']['error'] = error
            
            response_data = json.dumps(payload).encode()
            
            # Determine response subject based on stream type
            if response_stream == self.STREAM_RESPONSE_QUEUE:
                response_subject = self.response_queue
                stream_name = self.STREAM_RESPONSE_QUEUE
            elif response_stream == self.STREAM_RESPONSE_IMMEDIATE:
                response_subject = self.response_immediate
                stream_name = self.STREAM_RESPONSE_IMMEDIATE
            else:
                raise ValueError(f"Invalid response_stream: {response_stream}. Must be {self.STREAM_RESPONSE_QUEUE} or {self.STREAM_RESPONSE_IMMEDIATE}")
            
            # Publish to JetStream response stream
            await self.js.publish(response_subject, response_data)
            logger.info("Published command response to JetStream: stream=%s, subject=%s, run_id=%s, command_id=%s, status=%s", 
                       stream_name, response_subject, run_id, command_id, status)
        except Exception as e:
            logger.error("Error publishing command response: %s", e)
    
    async def process_queue_cmd(
        self, 
        msg: Msg,
        handler: Callable[[Dict[str, Any]], Awaitable[bool]]
    ) -> None:
        """
        Handle the lifecycle of a single message: Parse -> Handle -> Ack/Nak/Term.
        
        Args:
            msg: NATS message
            handler: Handler function to process the message
        """
        try:
            # Parse payload
            payload, run_id, command_id = self._parse_message(msg.data)
            header = payload.get('header', {})
            command = header.get('command', 'unknown')
            
            # Check if cancelled
            if run_id and run_id in self._cancelled_run_ids:
                logger.info("Skipping cancelled command: run_id=%s, command_id=%s, command=%s", run_id, command_id, command)
                await msg.ack()
                await self._publish_command_response(msg, 'error', 'Command cancelled', response_stream=self.STREAM_RESPONSE_QUEUE)
                await self.publish_state({'state': 'idle', 'run_id': run_id})
                return
            
            # Check if paused (for queue messages)
            async with self._pause_lock:
                while self._is_paused:
                    await msg.in_progress()
                    await asyncio.sleep(1)
                    # Re-check cancelled state in case it was cancelled while paused
                    if run_id and run_id in self._cancelled_run_ids:
                        logger.info("Command cancelled while paused: run_id=%s, command_id=%s, command=%s", run_id, command_id, command)
                        await msg.ack()
                        await self._publish_command_response(msg, 'error', 'Command cancelled', response_stream=self.STREAM_RESPONSE_QUEUE)
                        await self.publish_state({'state': 'idle', 'run_id': run_id})
                        return
            
            # Execute handler with auto-heartbeat (task might take a while for machine to complete)
            async with self._keep_message_alive(msg):
                success = await handler(payload)
            
            # Finalize message state
            if success:
                await msg.ack()
                await self._publish_command_response(msg, 'success', response_stream=self.STREAM_RESPONSE_QUEUE)
                await self.publish_state({'state': 'idle', 'run_id': run_id})
            else:
                await msg.term()
                await self._publish_command_response(msg, 'error', 'Handler returned False', response_stream=self.STREAM_RESPONSE_QUEUE)
                await self.publish_state({'state': 'error', 'run_id': run_id})

        except asyncio.CancelledError:
            # Handler was cancelled (e.g., via task cancellation)
            logger.info("Handler execution cancelled: run_id=%s, command_id=%s, command=%s", run_id, command_id, command)
            await msg.ack()
            await self._publish_command_response(msg, 'error', 'Command cancelled', response_stream=self.STREAM_RESPONSE_QUEUE)
            await self.publish_state({'state': 'idle', 'run_id': run_id})
        
        except json.JSONDecodeError as e:
            logger.error("JSON Decode Error. Terminating message.")
            await msg.term()
            await self._publish_command_response(msg, 'error', f'JSON decode error: {e}', response_stream=self.STREAM_RESPONSE_QUEUE)
            await self.publish_state({'state': 'error', 'run_id': run_id})
        
        except Exception as e:
            # Check if cancelled before sending error response
            if run_id and run_id in self._cancelled_run_ids:
                logger.info("Command cancelled during execution (exception occurred): run_id=%s, command_id=%s, command=%s", run_id, command_id, command)
                await msg.ack()
                await self._publish_command_response(msg, 'error', 'Command cancelled', response_stream=self.STREAM_RESPONSE_QUEUE)
                await self.publish_state({'state': 'idle', 'run_id': run_id})
            else:
                # Terminate all errors to prevent infinite redelivery loops
                logger.error("Handler failed (terminating message): %s", e)
                await msg.term()
                await self._publish_command_response(msg, 'error', str(e), response_stream=self.STREAM_RESPONSE_QUEUE)
                await self.publish_state({'state': 'error', 'run_id': run_id})
    
    async def process_immediate_cmd(self, msg: Msg, handler: Callable[[Dict[str, Any]], Awaitable[bool]]) -> None:
        """Process immediate commands (pause, cancel, resume, etc.)."""
        try:
            payload, run_id, _ = self._parse_message(msg.data)
            # Ack immediately after successful parse
            await msg.ack()
            
            header = payload.get('header', {})
            command = header.get('command', '').lower()
            
            # Handle built-in commands
            if command == 'pause':
                async with self._pause_lock:
                    if not self._is_paused:
                        self._is_paused = True
                        logger.info("Queue paused")
                        await self.publish_state({'state': 'paused', 'run_id': run_id})
                await self._publish_command_response(msg, 'success', response_stream=self.STREAM_RESPONSE_IMMEDIATE)
                return
            
            elif command == 'resume':
                async with self._pause_lock:
                    if self._is_paused:
                        self._is_paused = False
                        logger.info("Queue resumed")
                        await self.publish_state({'state': 'idle', 'run_id': None})
                        
                print(f"Publishing command: {msg.data}")
                await self._publish_command_response(msg, 'success', response_stream=self.STREAM_RESPONSE_IMMEDIATE)
                return
            
            elif command == 'cancel':
                if run_id:
                    self._cancelled_run_ids.add(run_id)
                    logger.info("Cancelling all commands with run_id: %s", run_id)
                    await self.publish_state({'state': 'idle', 'run_id': None})
                await self._publish_command_response(msg, 'success', response_stream=self.STREAM_RESPONSE_IMMEDIATE)
                return
            
            # For other immediate commands, call the user-provided handler
            async with self._keep_message_alive(msg):
                success = await handler(payload)
            
            if success:
                await self._publish_command_response(msg, 'success', response_stream=self.STREAM_RESPONSE_IMMEDIATE)
            else:
                await self._publish_command_response(msg, 'error', 'Handler returned False', response_stream=self.STREAM_RESPONSE_IMMEDIATE)
        
        except json.JSONDecodeError as e:
            logger.error("JSON Decode Error in immediate command: %s", e)
            await msg.term()
            await self._publish_command_response(msg, 'error', f'JSON decode error: {e}', response_stream=self.STREAM_RESPONSE_IMMEDIATE)
            await self.publish_state({'state': 'error', 'run_id': None})
        
        except Exception as e:
            logger.error("Error processing immediate command (terminating message): %s", e)
            await msg.term()
            await self._publish_command_response(msg, 'error', str(e), response_stream=self.STREAM_RESPONSE_IMMEDIATE)
            await self.publish_state({'state': 'error', 'run_id': None})
    
    async def subscribe_queue(self, handler: Callable[[Dict[str, Any]], Awaitable[bool]]):
        """
        Subscribe to queue commands with default consumer.
        
        Args:
            handler: Async function that processes command payloads (payload) -> bool
        """
        if not self.js:
            logger.error("JetStream not available for queue subscription")
            return
        
        # Ensure stream exists before attempting to subscribe
        await self._ensure_command_queue_stream()
        
        try:
            async def message_handler(msg: Msg):
                """Wrapper to process queue messages."""
                await self.process_queue_cmd(msg, handler)

            self._cmd_queue_sub = await self.js.subscribe(
                subject=self.cmd_queue,
                stream=self.STREAM_COMMAND_QUEUE,
                durable=f"cmd_queue_{self.machine_id}",
                cb=message_handler
            )
        except NotFoundError:
            # Stream still not found after ensuring it exists - this shouldn't happen
            # but handle it gracefully with detailed diagnostics
            logger.error("Stream %s not found when subscribing to %s. This may indicate:", 
                       self.STREAM_COMMAND_QUEUE, self.cmd_queue)
            logger.error("  1. Stream creation failed silently")
            logger.error("  2. Subject pattern mismatch (stream pattern: %s.*.cmd.queue, subject: %s)", 
                       self.NAMESPACE, self.cmd_queue)
            logger.error("  3. NATS cluster propagation delay")
            # Try to get stream info one more time for diagnostics
            try:
                stream_info = await self.js.stream_info(self.STREAM_COMMAND_QUEUE)
                logger.error("  Stream actually exists with subjects: %s", stream_info.config.subjects)
            except Exception as stream_check_error:
                logger.error("  Stream verification failed: %s", stream_check_error)
            raise
        
        # Register handler for reconnection
        if not any(h['type'] == 'queue' for h in self._reconnect_handlers):
            self._reconnect_handlers.append({'type': 'queue', 'handler': handler})
        logger.info("Subscribed to queue commands: %s (durable: cmd_queue_%s, stream: %s)", 
                   self.cmd_queue, self.machine_id, self.STREAM_COMMAND_QUEUE)
    
    async def subscribe_immediate(self, handler: Callable):
        """
        Subscribe to immediate commands with default consumer.
        
        Args:
            handler: Async function that processes command payloads (payload) -> bool
        """
        if not self.js:
            logger.error("JetStream not available for immediate subscription")
            return
        
        async def message_handler(msg: Msg):
            """Wrapper to process immediate messages."""
            await self.process_immediate_cmd(msg, handler)
        
        # Ensure stream exists before attempting to subscribe
        await self._ensure_command_immediate_stream()
        
        try:
            self._cmd_immediate_sub = await self.js.subscribe(
                subject=self.cmd_immediate,
                stream=self.STREAM_COMMAND_IMMEDIATE,
                durable=f"cmd_immed_{self.machine_id}",
                cb=message_handler
            )
        except NotFoundError:
            # Stream still not found after ensuring it exists - this shouldn't happen
            # but handle it gracefully
            logger.error("Stream %s not found even after creation attempt. Check NATS server configuration.", 
                       self.STREAM_COMMAND_IMMEDIATE)
            raise
        
        # Register handler for reconnection
        if not any(h['type'] == 'immediate' for h in self._reconnect_handlers):
            self._reconnect_handlers.append({'type': 'immediate', 'handler': handler})
        logger.info("Subscribed to immediate commands: %s (durable: cmd_immed_%s, stream: %s)", 
                   self.cmd_immediate, self.machine_id, self.STREAM_COMMAND_IMMEDIATE)
    
    
    # ==================== EVENTS (Core NATS, no JetStream) ====================
    
    async def publish_log(self, log_level: str, msg: str, **kwargs):
        """Publish log event (Core NATS, fire-and-forget)."""
        await self._publish_event(
            self.evt_log,
            {'log_level': log_level, 'msg': msg, **kwargs}
        )
    
    async def publish_alert(self, alert_type: str, severity: str, **kwargs):
        """Publish alert event for critical issues (Core NATS, fire-and-forget)."""
        await self._publish_event(
            self.evt_alert,
            {'type': alert_type, 'severity': severity, **kwargs}
        )
    
    async def publish_media(self, media_url: str, media_type: str = "image", **kwargs):
        """Publish media event after uploading to object storage (Core NATS, fire-and-forget)."""
        await self._publish_event(
            self.evt_media,
            {'media_url': media_url, 'media_type': media_type, **kwargs}
        )
