"""
Basic default NATS Client for Generic Machines
Handles commands, telemetry, and events following the puda.{machine_id}.{category}.{sub_category} pattern
Specific methods to a single machine should be implemented in the machine-edge client
"""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone
import nats
from .models import (
    CommandResponseStatus,
    CommandResponse,
    CommandResponseCode,
    NATSMessage,
    CommandRequest,
    MessageType,
    ImmediateCommand,
)
from .run_manager import RunManager
from nats.js.client import JetStreamContext
from nats.js.api import StreamConfig, ConsumerConfig
from nats.js.errors import NotFoundError, Error as NATSError
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
        self._cmd_queue_task = None  # Background task for pull consumer
        self._cmd_immediate_sub = None
        
        # Connection state
        self._is_connected = False
        self._queue_handler = None
        self._immediate_handler = None
        
        # Queue control state
        self._pause_lock = asyncio.Lock()
        self._is_paused = False
        
        # Run state management
        self.run_manager = RunManager(machine_id=machine_id)
    
    def _init_subjects(self):
        """Initialize all subject and stream names."""
        namespace = self.NAMESPACE
        machine_id_safe = self.machine_id.replace('.', '-')
        
        # Telemetry subjects (core NATS, no JetStream)
        self.tlm_heartbeat = f"{namespace}.{machine_id_safe}.tlm.heartbeat"
        self.tlm_pos = f"{namespace}.{machine_id_safe}.tlm.pos"
        self.tlm_health = f"{namespace}.{machine_id_safe}.tlm.health"
        
        # Command subjects (JetStream, exactly-once)
        self.cmd_queue = f"{namespace}.{machine_id_safe}.cmd.queue" # should be pull consumer
        self.cmd_immediate = f"{namespace}.{machine_id_safe}.cmd.immediate" # push consumer
        
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
    
    async def _publish_telemetry(self, subject: str, data: Dict[str, Any]) -> bool:
        """Publish telemetry message to core NATS."""
        if not self.nc:
            logger.warning("NATS not connected, skipping %s", subject)
            return False
        
        try:
            message = {'timestamp': self._format_timestamp(), **data}
            await self.nc.publish(subject=subject, payload=json.dumps(message).encode())
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
            await self.nc.publish(subject=subject, payload=json.dumps(message).encode())
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
                await self.js.update_stream(config=updated_config)
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
    
    async def _ensure_all_streams(self):
        """Ensure all required streams exist with correct retention policies."""
        await self._ensure_stream(
            self.STREAM_COMMAND_QUEUE,
            f"{self.NAMESPACE}.*.cmd.queue",
            retention='workqueue'
        )
        await self._ensure_stream(
            self.STREAM_COMMAND_IMMEDIATE,
            f"{self.NAMESPACE}.*.cmd.immediate"
        )
        await self._ensure_stream(
            self.STREAM_RESPONSE_QUEUE,
            f"{self.NAMESPACE}.*.cmd.response.queue",
            retention='interest'
        )
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
        # Clean up queue subscription (pull consumer)
        if self._cmd_queue_task:
            try:
                self._cmd_queue_task.cancel()
                await self._cmd_queue_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._cmd_queue_task = None
        
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
        self._cmd_queue_task = None
        self._cmd_immediate_sub = None
    
    # ==================== CONNECTION MANAGEMENT ====================
    
    async def connect(self) -> bool:
        """Connect to NATS server and initialize JetStream with auto-reconnection."""
        try:
            self.nc = await nats.connect(
                servers=self.servers,
                connect_timeout=10,  # 10 seconds timeout for initial connection
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback
            )
            self.js = self.nc.jetstream()
            await self._ensure_all_streams()
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
            await self._ensure_all_streams()
            self.kv = await self._get_or_create_kv_bucket()
            await self._resubscribe_handlers()
    
    async def _resubscribe_handlers(self):
        """Re-subscribe to all handlers after reconnection."""
        if self._queue_handler:
            await self.subscribe_queue(self._queue_handler)
        if self._immediate_handler:
            await self.subscribe_immediate(self._immediate_handler)
    
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
            data: Dictionary with state data
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
        response: CommandResponse,
        subject: str
    ):
        """
        Publish command response message to JetStream response stream.
        
        Args:
            msg: NATS message
            response: CommandResponse object containing status, code, message, and completed_at
            subject: NATS subject to publish the response to
        """
        if not self.js:
            return
        
        try:
            original_message = NATSMessage.model_validate_json(msg.data)
            
            # Create response message with RESPONSE type
            response_header = original_message.header.model_copy(
                update={
                    'message_type': MessageType.RESPONSE,
                    'timestamp': self._format_timestamp()
                }
            )
            response_message = original_message.model_copy(
                update={'header': response_header, 'response': response}
            )
            
            # Publish to JetStream response stream
            await self.js.publish(subject=subject, payload=response_message.model_dump_json().encode())
            logger.info("Published command response to JetStream: %s", response_message.model_dump_json())
        except Exception as e:
            logger.error("Error publishing command response: %s", e)
    
    async def process_queue_cmd(
        self,
        msg: Msg,
        handler: Callable[[NATSMessage], Awaitable[CommandResponse]]
    ) -> None:
        """
        Handle the lifecycle of a single message: Parse -> Handle -> Ack/Nak/Term.
        
        Args:
            msg: NATS message
            handler: Handler function that processes the message and returns a CommandResponse object
        """
        # Initialize variables for exception handlers
        run_id = None
        step_number = None
        command = None
        
        try:
            # Parse message
            message = NATSMessage.model_validate_json(msg.data)
            run_id = message.header.run_id
            step_number = message.command.step_number if message.command else None
            command = message.command.name if message.command else None
            
            # For all commands, continue with normal processing:
            # 1. Check if paused
            # 2. Validate run_id matches active run
            # 3. Execute handler
            
            # If machine is paused, publish error response and return
            async with self._pause_lock:
                if self._is_paused:
                    await self._publish_command_response(
                        msg,
                        CommandResponse(
                            status=CommandResponseStatus.ERROR,
                            code=CommandResponseCode.MACHINE_PAUSED,
                            message='Machine paused'
                        ),
                        subject=self.response_queue
                    )
                    return
            
            # Wait while paused (release lock during wait so RESUME can acquire it)
            while True:
                async with self._pause_lock:
                    if not self._is_paused:
                        break
                # Release lock before sleeping so RESUME can set _is_paused = False
                await msg.in_progress()
                await asyncio.sleep(1)
            
            # Validate run_id matches active run (run_id is required)
            if run_id is None:
                await msg.ack()
                await self._publish_command_response(
                    msg=msg,
                    response=CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.EXECUTION_ERROR,
                        message='Command requires run_id'
                    ),
                    subject=self.response_queue
                )
                return
            
            # If active run_id is None, return error response
            if self.run_manager.get_active_run_id() is None:
                await msg.ack()
                await self._publish_command_response(
                    msg=msg,
                    response=CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.RUN_ID_MISMATCH,
                        message='Send START command to start a run before sending commands'
                    ),
                    subject=self.response_queue
                )
                return
            
            # If run_id does not match active run_id, return error response
            if not await self.run_manager.validate_run_id(run_id):
                await msg.ack()
                await self._publish_command_response(
                    msg=msg,
                    response=CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.RUN_ID_MISMATCH,
                        message=f'Run ID mismatch: expected active run, got {run_id}'
                    ),
                    subject=self.response_queue
                )
                return
            
            # Execute handler with auto-heartbeat (task might take a while for machine to complete)
            # The handler should be defined in the machine-specific edge module.
            async with self._keep_message_alive(msg):
                response: CommandResponse = await handler(message)
            
            # Finalize message state based on response
            if response.status == CommandResponseStatus.SUCCESS:
                await msg.ack()
            elif response.status == CommandResponseStatus.ERROR:
                # just complete the run if the command failed
                await self.run_manager.complete_run(run_id)
                await msg.term()
            
            await self._publish_command_response(
                msg=msg,
                response=response,
                subject=self.response_queue
            )
            # Note: Final state update should be published by the handler with machine-specific data

        except asyncio.CancelledError:
            # Handler was cancelled (e.g., via task cancellation)
            logger.info("Handler execution cancelled: run_id=%s, step_number=%s, command=%s", run_id, step_number, command)
            await msg.ack()
            await self.run_manager.complete_run(run_id)
            await self._publish_command_response(
                msg=msg,
                response=CommandResponse(
                    status=CommandResponseStatus.ERROR,
                    code=CommandResponseCode.COMMAND_CANCELLED,
                    message='Command cancelled'
                ),
                subject=self.response_queue
            )
            # Note: Final state update should be published by the handler with machine-specific data
        
        except json.JSONDecodeError as e:
            logger.error("JSON Decode Error. Terminating message.")
            await msg.term()
            await self.run_manager.complete_run(run_id)
            await self._publish_command_response(
                msg=msg,
                response=CommandResponse(
                    status=CommandResponseStatus.ERROR,
                    code=CommandResponseCode.JSON_DECODE_ERROR,
                    message=f'JSON decode error: {e}'
                ),
                subject=self.response_queue
            )
            # Note: Final state update should be published by the handler with machine-specific data
            # For JSON decode errors, handler wasn't called, so we can't rely on it
            # This is a rare case - consider if handler should be called with None payload
        
        except Exception as e:
            # Terminate all errors to prevent infinite redelivery loops
            logger.error("Handler failed (terminating message): %s", e)
            await msg.term()
            await self.run_manager.complete_run(run_id)
            await self._publish_command_response(
                msg=msg,
                response=CommandResponse(
                    status=CommandResponseStatus.ERROR,
                    code=CommandResponseCode.EXECUTION_ERROR,
                    message=str(e)
                ),
                subject=self.response_queue
            )
            # Note: Final state update should be published by the handler with machine-specific data
    
    async def process_immediate_cmd(self, msg: Msg, handler: Callable[[CommandRequest], Awaitable[CommandResponse]]) -> None:
        """Process immediate commands (pause, cancel, resume, etc.)."""
        try:
            message = NATSMessage.model_validate_json(msg.data)
            # Ack immediately after successful parse
            await msg.ack()
            
            # Handle built-in commands
            if message.command is None:
                logger.error("Received message with no command")
                return
            
            command_name = message.command.name.lower()
            run_id = message.header.run_id
            response: CommandResponse
            
            match command_name:
                case ImmediateCommand.START:
                    if run_id:
                        success = await self.run_manager.start_run(run_id)
                        if not success:
                            # Run already active
                            response = CommandResponse(
                                status=CommandResponseStatus.ERROR,
                                code=CommandResponseCode.RUN_ID_MISMATCH,
                                message=f'cannot start, {self.run_manager.get_active_run_id()} is currently running'
                            )
                        else:
                            await self.publish_state({'state': 'active', 'run_id': run_id})
                            response = CommandResponse(status=CommandResponseStatus.SUCCESS)
                    else:
                        response = CommandResponse(
                            status=CommandResponseStatus.ERROR,
                            code=CommandResponseCode.MISSING_RUN_ID,
                            message='START command requires RUN_ID'
                        )
                
                case ImmediateCommand.COMPLETE:
                    if not run_id:
                        response = CommandResponse(
                            status=CommandResponseStatus.ERROR,
                            code=CommandResponseCode.MISSING_RUN_ID,
                            message='COMPLETE command requires RUN_ID'
                        )
                    else:
                        success = await self.run_manager.complete_run(run_id)
                        if success:
                            await self.publish_state({'state': 'idle', 'run_id': None})
                            response = CommandResponse(status=CommandResponseStatus.SUCCESS)
                        else:
                            response = CommandResponse(
                                status=CommandResponseStatus.ERROR,
                                code=CommandResponseCode.RUN_ID_MISMATCH,
                                message=f'Run {run_id} not active'
                            )
                
                case ImmediateCommand.PAUSE:
                    async with self._pause_lock:
                        if not self._is_paused:
                            self._is_paused = True
                            logger.info("Queue paused")
                            await self.publish_state({'state': 'paused', 'run_id': message.header.run_id})
                    # Call handler and use its response
                    response = await handler(message)
                
                case ImmediateCommand.RESUME:
                    async with self._pause_lock:
                        if self._is_paused:
                            self._is_paused = False
                            logger.info("Queue resumed")
                            await self.publish_state({'state': 'idle', 'run_id': None})
                    # Call handler and use its response
                    response = await handler(message)
                
                case ImmediateCommand.CANCEL:
                    if not run_id:
                        response = CommandResponse(
                            status=CommandResponseStatus.ERROR,
                            code=CommandResponseCode.MISSING_RUN_ID,
                            message='CANCEL command requires RUN_ID'
                        )
                    else:
                        logger.info("Cancelling all commands with run_id: %s", run_id)
                        # Clear the active run_id when cancelling (try to complete, but clear anyway)
                        await self.run_manager.complete_run(run_id)
                        await self.publish_state({'state': 'idle', 'run_id': None})
                        # Call handler and use its response
                        response = await handler(message)
                
                case _:
                    # Unknown immediate command
                    response = CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.UNKNOWN_COMMAND,
                        message=f'Unknown immediate command: {command_name}'
                    )
            
            await self._publish_command_response(
                msg=msg,
                response=response,
                subject=self.response_immediate
            )
        
        except json.JSONDecodeError as e:
            logger.error("JSON Decode Error in immediate command: %s", e)
            # msg.ack() was already called, so we just need to publish error response
            await self._publish_command_response(
                msg=msg,
                response=CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.JSON_DECODE_ERROR,
                        message=f'JSON decode error: {e}'
                    ),
                subject=self.response_immediate
            )
            await self.publish_state({'state': 'error', 'run_id': None})
        
        except Exception as e:
            # msg.ack() was already called, so we just publish error response
            logger.error("Error processing immediate command: %s", e)
            await self._publish_command_response(
                msg=msg,
                response=CommandResponse(
                    status=CommandResponseStatus.ERROR,
                    code=CommandResponseCode.EXECUTION_ERROR,
                    message=str(e)
                ),
                subject=self.response_immediate
            )
            await self.publish_state({'state': 'error', 'run_id': None})
    
    async def _verify_or_recreate_consumer(self, durable_name: str):
        """
        Check if consumer exists and verify/update its configuration.
        Deletes and recreates the consumer if configuration doesn't match.
        
        Args:
            durable_name: Name of the durable consumer to verify
        """
        # Check if consumer exists and verify/update its configuration
        try:
            consumer_info = await self.js.consumer_info(self.STREAM_COMMAND_QUEUE, durable_name)
            logger.debug("Durable consumer %s already exists", durable_name)
            
            # Check if consumer config matches what we need
            config = consumer_info.config
            needs_recreate = False
            if getattr(config, 'filter_subject', None) != self.cmd_queue:
                logger.warning("Consumer filter_subject mismatch: expected %s, got %s", 
                             self.cmd_queue, getattr(config, 'filter_subject', None))
                needs_recreate = True
            if getattr(config, 'ack_policy', None) != 'explicit':
                logger.warning("Consumer ack_policy mismatch: expected explicit, got %s", 
                             getattr(config, 'ack_policy', None))
                needs_recreate = True
            if getattr(config, 'deliver_policy', None) != 'all':
                logger.warning("Consumer deliver_policy mismatch: expected all, got %s", 
                             getattr(config, 'deliver_policy', None))
                needs_recreate = True
            
            if needs_recreate:
                # Consumer exists but config doesn't match - delete and recreate
                logger.info("Consumer config mismatch, deleting and recreating: %s", durable_name)
                try:
                    await self.js.delete_consumer(self.STREAM_COMMAND_QUEUE, durable_name)
                except Exception as e:
                    logger.warning("Error deleting consumer: %s", e)
            else:
                # Log consumer state for diagnostics
                logger.info("Consumer exists with correct config - pending: %d, delivered: %d, ack_pending: %d",
                           consumer_info.num_pending, consumer_info.delivered.consumer_seq,
                           consumer_info.num_ack_pending)
        except NotFoundError:
            # Consumer doesn't exist, will be created by pull_subscribe
            logger.debug("Durable consumer %s does not exist, will be created", durable_name)
    
    async def subscribe_queue(self, handler: Callable[[NATSMessage], Awaitable[CommandResponse]]):
        """
        Subscribe to queue commands with pull consumer.
        
        Args:
            handler: Async function that processes command payloads and returns CommandResponse
        """
        if not self.js:
            logger.error("JetStream not available for queue subscription")
            return

        # Store handler for reconnection
        self._queue_handler = handler
        
        # Ensure stream exists before attempting to subscribe
        await self._ensure_all_streams()
        
        try:
            durable_name = f"cmd_queue_{self.machine_id}"
            
            await self._verify_or_recreate_consumer(durable_name)
            
            # Create pull subscription - this will create the consumer if it doesn't exist
            # Pass config directly to ensure correct consumer configuration
            consumer_config = ConsumerConfig(
                durable_name=durable_name,
                filter_subject=self.cmd_queue,
                ack_policy="explicit",
                deliver_policy="all",  # Required for WorkQueue: deliver all messages from the beginning
            )
            
            self._cmd_queue_sub = await self.js.pull_subscribe(
                subject=self.cmd_queue,
                durable=durable_name,
                stream=self.STREAM_COMMAND_QUEUE,
                config=consumer_config
            )
            
            # Log final consumer info for diagnostics
            try:
                consumer_info = await self.js.consumer_info(self.STREAM_COMMAND_QUEUE, durable_name)
                logger.info("Pull subscription created - subject: %s, durable: %s, stream: %s, pending: %d, ack_pending: %d",
                           self.cmd_queue, durable_name, self.STREAM_COMMAND_QUEUE,
                           consumer_info.num_pending, consumer_info.num_ack_pending)
            except Exception as e:
                logger.warning("Could not get consumer info after subscription: %s", e)
                logger.info("Pull subscription created - subject: %s, durable: %s, stream: %s",
                           self.cmd_queue, durable_name, self.STREAM_COMMAND_QUEUE)
            
            # Start background task to pull and process messages
            async def pull_messages():
                """Continuously pull messages from the queue."""
                try:
                    while True:
                        try:
                            # Fetch one message (timeout 1 second)
                            msgs = await self._cmd_queue_sub.fetch(batch=1, timeout=1.0)
                            if msgs:
                                logger.debug("Pulled message from queue")
                                await self.process_queue_cmd(msgs[0], handler)
                        except asyncio.TimeoutError:
                            # Timeout is expected when no messages are available
                            continue
                        except Exception as e:
                            logger.error("Error pulling queue messages: %s", e, exc_info=True)
                            await asyncio.sleep(1)  # Wait before retrying
                except asyncio.CancelledError:
                    logger.debug("Queue pull task cancelled")
                    raise
            
            self._cmd_queue_task = asyncio.create_task(pull_messages())
            logger.info("Started background task for pulling queue messages")
            
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
        
        logger.info("Subscribed to queue commands: %s (durable: cmd_queue_%s, stream: %s, pull consumer)", 
                   self.cmd_queue, self.machine_id, self.STREAM_COMMAND_QUEUE)
    
    async def subscribe_immediate(self, handler: Callable[[NATSMessage], Awaitable[CommandResponse]]):
        """
        Subscribe to immediate commands with default consumer.
        
        Args:
            handler: Async function that processes command payloads (payload) -> bool
        """
        if not self.js:
            logger.error("JetStream not available for immediate subscription")
            return
        
        # Store handler for use in callback and reconnection
        self._immediate_handler = handler
        
        async def message_handler(msg: Msg):
            """Process immediate messages using stored handler."""
            await self.process_immediate_cmd(msg, self._immediate_handler)
        
        # Ensure stream exists before attempting to subscribe
        await self._ensure_stream(
            self.STREAM_COMMAND_IMMEDIATE,
            f"{self.NAMESPACE}.*.cmd.immediate",
            retention='workqueue'
        )
        
        durable_name = f"cmd_immed_{self.machine_id}"
        
        # Try to unsubscribe from existing subscription if it exists
        if self._cmd_immediate_sub:
            try:
                await self._cmd_immediate_sub.unsubscribe()
                logger.info("Unsubscribed from existing immediate command subscription")
            except Exception as e:
                logger.debug("Error unsubscribing from existing subscription: %s", e)
            self._cmd_immediate_sub = None
        
        # Try to delete existing consumer if it's bound (from previous run)
        try:
            await self.js.delete_consumer(self.STREAM_COMMAND_IMMEDIATE, durable_name)
            logger.info("Deleted existing immediate consumer: %s", durable_name)
        except NotFoundError:
            # Consumer doesn't exist, which is fine
            logger.debug("Consumer %s does not exist, will be created", durable_name)
        except Exception as e:
            error_msg = str(e).lower()
            if "bound" in error_msg or "in use" in error_msg:
                # Consumer is bound but we can't delete it - try to unsubscribe first
                logger.warning("Consumer %s is bound to a subscription. Attempting to force delete...", durable_name)
                # Wait a moment for any pending operations to complete
                await asyncio.sleep(0.5)
                try:
                    await self.js.delete_consumer(self.STREAM_COMMAND_IMMEDIATE, durable_name)
                    logger.info("Successfully deleted bound consumer: %s", durable_name)
                except Exception as delete_error:
                    logger.warning("Could not delete bound consumer %s: %s. Will attempt to subscribe anyway.", 
                                 durable_name, delete_error)
            else:
                logger.warning("Error checking/deleting consumer %s: %s", durable_name, e)
        
        try:
            self._cmd_immediate_sub = await self.js.subscribe(
                subject=self.cmd_immediate,
                stream=self.STREAM_COMMAND_IMMEDIATE,
                durable=durable_name,
                cb=message_handler  # required for push consumer to handle messages
            )
        except NATSError as e:
            error_msg = str(e).lower()
            if "bound" in error_msg or "already bound" in error_msg:
                # Consumer is still bound - try to delete it and retry
                logger.warning("Consumer %s is still bound. Attempting to delete and retry...", durable_name)
                try:
                    await self.js.delete_consumer(self.STREAM_COMMAND_IMMEDIATE, durable_name)
                    await asyncio.sleep(0.5)  # Brief wait for cleanup
                    # Retry subscription
                    self._cmd_immediate_sub = await self.js.subscribe(
                        subject=self.cmd_immediate,
                        stream=self.STREAM_COMMAND_IMMEDIATE,
                        durable=durable_name,
                        cb=message_handler
                    )
                    logger.info("Successfully subscribed after deleting bound consumer")
                except Exception as retry_error:
                    logger.error("Failed to subscribe after deleting bound consumer: %s", retry_error)
                    raise
            else:
                raise
        except NotFoundError:
            # Stream still not found after ensuring it exists - this shouldn't happen
            # but handle it gracefully
            logger.error("Stream %s not found even after creation attempt. Check NATS server configuration.",
                       self.STREAM_COMMAND_IMMEDIATE)
            raise
        
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
