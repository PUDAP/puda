"""
NATS Client for Generic Machines
Handles commands, telemetry, and events following the puda.{machine_id}.{category}.{sub_category} pattern
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone
import nats
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError

logger = logging.getLogger(__name__)


class MachineNATSClient:
    """
    NATS client for machines.
    
    Subject pattern: puda.{machine_id}.{category}.{sub_category}
    - Telemetry: core NATS (no JetStream)
    - Commands: JetStream with exactly-once delivery (run_id)
    - Events: JetStream for persistence
    """
    
    def __init__(self, servers: list[str], machine_id: str):
        """
        Initialize NATS client for Opentron machine.
        
        Args:
            servers: List of NATS server URLs (e.g., ["nats://localhost:4222"])
            machine_id: Machine identifier (e.g., "opentron" or "opentron.ot-1")
        """
        self.servers = servers
        self.machine_id = machine_id
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self.kv = None
        
        # Subject patterns: puda.{machine_id}.{category}.{sub_category}
        namespace = "puda"
        
        # Telemetry subjects (core NATS, no JetStream)
        self.tlm_heartbeat = f"{namespace}.{machine_id}.tlm.heartbeat"
        self.tlm_pos = f"{namespace}.{machine_id}.tlm.pos"
        self.tlm_health = f"{namespace}.{machine_id}.tlm.health"
        self.tlm_status = f"{namespace}.{machine_id}.tlm.status"
        
        # Command subjects (JetStream, exactly-once with run_id)
        self.cmd_execute = f"{namespace}.{machine_id}.cmd.execute"
        self.cmd_pause = f"{namespace}.{machine_id}.cmd.pause"
        self.cmd_cancel = f"{namespace}.{machine_id}.cmd.cancel"
        
        # Event subjects (JetStream)
        self.evt_log = f"{namespace}.{machine_id}.evt.log"
        self.evt_alert = f"{namespace}.{machine_id}.evt.alert"
        self.evt_media = f"{namespace}.{machine_id}.evt.media"
        
        # KV bucket name for status (alternative to pub/sub)
        self.kv_bucket_name = f"MACHINE_STATE_{machine_id.replace('.', '_')}"
        
        # Subscriptions
        self._subscriptions = []
        self._js_subscriptions = []
        
        # Connection state
        self._is_connected = False
        self._reconnect_handlers = []  # Store handlers to re-subscribe on reconnect
    
    async def connect(self) -> bool:
        """Connect to NATS server and initialize JetStream with auto-reconnection"""
        try:
            # Configure connection with auto-reconnection
            self.nc = await nats.connect(
                servers=self.servers,
                reconnect_time_wait=2,  # Wait 2 seconds between reconnection attempts
                max_reconnect_attempts=-1,  # Unlimited reconnection attempts
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback
            )
            self.js = self.nc.jetstream()
            
            # Create KV bucket for status if it doesn't exist
            try:
                self.kv = await self.js.create_key_value(
                    bucket=self.kv_bucket_name
                )
                logger.info("Created KV bucket: %s", self.kv_bucket_name)
            except Exception as e:
                # Bucket might already exist, try to get it
                try:
                    self.kv = await self.js.key_value(self.kv_bucket_name)
                    logger.info("Accessed existing KV bucket: %s", self.kv_bucket_name)
                except Exception:
                    logger.warning("Could not create or access KV bucket: %s", e)
                    self.kv = None
            
            self._is_connected = True
            logger.info("Connected to NATS servers: %s", self.servers)
            return True
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", e)
            self._is_connected = False
            return False
    
    async def _error_callback(self, error: Exception):
        """Callback for NATS errors"""
        logger.error("NATS error: %s", error)
    
    async def _disconnected_callback(self):
        """Callback when disconnected from NATS"""
        logger.warning("Disconnected from NATS servers")
        self._is_connected = False
        self.js = None
        self.kv = None
    
    async def _reconnected_callback(self):
        """Callback when reconnected to NATS"""
        logger.info("Reconnected to NATS servers")
        self._is_connected = True
        
        # Re-initialize JetStream context
        if self.nc:
            self.js = self.nc.jetstream()
            
            # Re-access KV bucket
            try:
                self.kv = await self.js.key_value(self.kv_bucket_name)
                logger.info("Re-accessed KV bucket: %s", self.kv_bucket_name)
            except Exception as e:
                logger.warning("Could not re-access KV bucket: %s", e)
                self.kv = None
            
            # Clear old JetStream subscriptions (they're invalid after reconnect)
            self._js_subscriptions.clear()
            
            # Re-subscribe to JetStream subscriptions
            # Note: Core NATS subscriptions are automatically restored
            for handler_info in self._reconnect_handlers:
                try:
                    handler_type = handler_info['type']
                    handler = handler_info['handler']
                    
                    if handler_type == 'execute':
                        await self.subscribe_execute(handler)
                    elif handler_type == 'pause':
                        await self.subscribe_pause(handler)
                    elif handler_type == 'cancel':
                        await self.subscribe_cancel(handler)
                except Exception as e:
                    logger.error("Failed to re-subscribe %s: %s", handler_type, e)
    
    async def _closed_callback(self):
        """Callback when connection is closed"""
        logger.info("NATS connection closed")
        self._is_connected = False
        self.js = None
        self.kv = None
    
    async def disconnect(self):
        """Disconnect from NATS server"""
        # Unsubscribe from all subscriptions
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        
        for sub in self._js_subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        
        if self.nc:
            await self.nc.close()
            self._is_connected = False
            logger.info("Disconnected from NATS")
    
    # ==================== TELEMETRY (Core NATS, no JetStream) ====================
    
    async def publish_heartbeat(self, timestamp: Optional[datetime] = None):
        """
        Publish heartbeat telemetry (timestamp only).
        
        Args:
            timestamp: Optional timestamp (defaults to now)
        """
        if not self.nc:
            logger.warning("NATS not connected, skipping heartbeat")
            return
        
        try:
            message = {
                'timestamp': (timestamp or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
            await self.nc.publish(
                self.tlm_heartbeat,
                json.dumps(message).encode()
            )
            logger.debug("Published heartbeat: %s", self.tlm_heartbeat)
        except Exception as e:
            logger.error("Error publishing heartbeat: %s", e)
    
    async def publish_position(self, coords: Dict[str, float]):
        """
        Publish real-time position coordinates.
        
        Args:
            coords: Dictionary with position data (e.g., {'x': 0.0, 'y': 0.0, 'z': 0.0})
        """
        if not self.nc:
            logger.warning("NATS not connected, skipping position")
            return
        
        try:
            message = {
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                **coords
            }
            await self.nc.publish(
                self.tlm_pos,
                json.dumps(message).encode()
            )
            logger.debug("Published position: %s", self.tlm_pos)
        except Exception as e:
            logger.error("Error publishing position: %s", e)
    
    async def publish_health(self, vitals: Dict[str, Any]):
        """
        Publish system health vitals (CPU, memory, temperature, etc.).
        
        Args:
            vitals: Dictionary with system vitals (e.g., {'cpu': 45.2, 'mem': 60.1, 'temp': 35.0})
        """
        if not self.nc:
            logger.warning("NATS not connected, skipping health")
            return
        
        try:
            message = {
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                **vitals
            }
            await self.nc.publish(
                self.tlm_health,
                json.dumps(message).encode()
            )
            logger.debug("Published health: %s", self.tlm_health)
        except Exception as e:
            logger.error("Error publishing health: %s", e)
    
    async def publish_status(self, status_data: Dict[str, Any]):
        """
        Update machine status in KV store.
        
        Args:
            status_data: Dictionary with status data (e.g., {'state': 'idle', 'run_id': 'abc123'})
                - state: 'idle', 'busy', or 'error'
                - run_id: Current run_id if busy/error, None if idle
        """
        if not self.kv:
            logger.warning("KV store not available, skipping status update")
            return
        
        try:
            message = {
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                **status_data
            }
            
            # Update status in KV store
            await self.kv.put(
                self.machine_id,
                json.dumps(message).encode()
            )
            logger.info("Updated status in KV store: state=%s, run_id=%s", 
                       status_data.get('state'), status_data.get('run_id'))
        except Exception as e:
            logger.error("Error updating status in KV store: %s", e)
    
    # ==================== COMMANDS (JetStream, exactly-once with run_id) ====================
    
    async def _ensure_stream(self, subject: str, stream_name: str):
        """Ensure a JetStream stream exists for the given subject"""
        try:
            await self.js.stream_info(stream_name)
            logger.debug("Stream already exists: %s", stream_name)
        except NotFoundError:
            # Stream doesn't exist, create it
            await self.js.add_stream(
                name=stream_name,
                subjects=[subject]
            )
            logger.info("Created stream: %s for subject: %s", stream_name, subject)
        except Exception as e:
            logger.warning("Could not ensure stream %s: %s", stream_name, e)
    
    async def _subscribe_command(
        self,
        command_type: str,
        subject: str,
        handler: Callable[[Dict[str, Any]], Awaitable[bool]]
    ):
        """
        Generic method to subscribe to command messages.
        
        Args:
            command_type: Type of command ('execute', 'pause', 'cancel')
            subject: NATS subject to subscribe to
            handler: Handler function that receives JSON payload and returns bool.
                     Returns True on success, False on error, or raises exception.
                     Signature: (payload) -> bool
        """
        if not self.js:
            logger.error("JetStream not available, cannot subscribe to %s commands", command_type)
            return
        
        async def message_handler(msg):
            run_id = None
            try:
                # Parse Envelope Pattern payload
                payload = json.loads(msg.data.decode())
                
                # Extract run_id for status updates
                run_id = payload.get('header', {}).get('run_id', 'unknown')
                
                # Update status to busy when command starts
                await self.publish_status({'state': 'busy', 'run_id': run_id})
                
                # Handler returns True on success, False on error, or raises exception
                result = await handler(payload)
                
                # Handle ack/nak and status based on handler return value
                if result is True:
                    # Command succeeded
                    await self.publish_status({'state': 'idle', 'run_id': run_id})
                    await msg.ack()
                else:
                    # Command failed (returned False)
                    await self.publish_status({'state': 'error', 'run_id': run_id})
                    await msg.nak()
                
            except json.JSONDecodeError as e:
                logger.error("Failed to decode JSON: %s", e)
                if run_id:
                    await self.publish_status({'state': 'error', 'run_id': run_id})
                await msg.nak()
            except Exception as e:
                logger.error("Unexpected error in %s command handler: %s", command_type, e)
                if run_id:
                    await self.publish_status({'state': 'error', 'run_id': run_id})
                try:
                    await msg.nak()
                except Exception:
                    pass  # Message might already be acked/naked
        
        try:
            stream_name = f"CMD_{command_type.upper()}_{self.machine_id.replace('.', '_')}"
            await self._ensure_stream(subject, stream_name)
            
            consumer_name = f"{self.machine_id}_{command_type}"
            try:
                await self.js.add_consumer(
                    stream_name,
                    durable=consumer_name,
                    config={
                        'deliver_policy': 'all',
                        'ack_policy': 'explicit',
                        'max_deliver': 3,
                        'deliver_subject': None,  # Pull mode
                    }
                )
            except Exception:
                # Consumer might already exist
                pass
            
            sub = await self.js.pull_subscribe(
                subject,
                durable=consumer_name
            )
            self._js_subscriptions.append(sub)
            
            asyncio.create_task(self._consume_messages(sub, message_handler))
            
            # Store handler for reconnection (avoid duplicates)
            if not any(h['type'] == command_type for h in self._reconnect_handlers):
                self._reconnect_handlers.append({'type': command_type, 'handler': handler})
            
            logger.info("Subscribed to %s commands: %s", command_type, subject)
        except Exception as e:
            logger.error("Failed to subscribe to %s commands: %s", command_type, e)
    
    async def subscribe_execute(
        self,
        handler: Callable[[Dict[str, Any]], Awaitable[bool]]
    ):
        """
        Subscribe to execute commands using JetStream WorkQueue (ordered).
        
        Args:
            handler: Async function that takes (payload) -> bool
                payload: Parsed JSON dictionary with envelope pattern (header, params)
                Returns True on success, False on error, or raises exception
        """
        await self._subscribe_command('execute', self.cmd_execute, handler)
    
    async def subscribe_pause(
        self,
        handler: Callable[[Dict[str, Any]], Awaitable[bool]]
    ):
        """
        Subscribe to pause commands (direct, not WorkQueue).
        
        Args:
            handler: Async function that takes (payload) -> bool
                payload: Parsed JSON dictionary with envelope pattern (header, params)
                Returns True on success, False on error, or raises exception
        """
        await self._subscribe_command('pause', self.cmd_pause, handler)
    
    async def subscribe_cancel(
        self,
        handler: Callable[[Dict[str, Any]], Awaitable[bool]]
    ):
        """
        Subscribe to cancel commands (direct, not WorkQueue).
        
        Args:
            handler: Async function that takes (payload) -> bool
                payload: Parsed JSON dictionary with envelope pattern (header, params)
                Returns True on success, False on error, or raises exception
        """
        await self._subscribe_command('cancel', self.cmd_cancel, handler)
    
    async def _consume_messages(self, sub, handler):
        """Continuously consume messages from a pull subscription"""
        while True:
            try:
                msgs = await sub.fetch(1, timeout=1.0)
                for msg in msgs:
                    await handler(msg)
            except TimeoutError:
                # No messages available, continue
                continue
            except Exception as e:
                logger.error("Error consuming messages: %s", e)
                await asyncio.sleep(1)
    
    # ==================== EVENTS (JetStream) ====================
    
    async def publish_log(self, log_level: str, msg: str, **kwargs):
        """
        Publish log event.
        
        Args:
            log_level: Log level (e.g., 'INFO', 'WARNING', 'ERROR')
            msg: Log message
            **kwargs: Additional log data
        """
        if not self.js:
            logger.warning("JetStream not available, skipping log")
            return
        
        try:
            # Ensure stream exists for log events
            stream_name = f"EVT_LOG_{self.machine_id.replace('.', '_')}"
            await self._ensure_stream(self.evt_log, stream_name)
            
            message = {
                'log_level': log_level,
                'msg': msg,
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                **kwargs
            }
            await self.js.publish(
                self.evt_log,
                json.dumps(message).encode()
            )
            logger.debug("Published log (%s): %s", log_level, self.evt_log)
        except Exception as e:
            logger.error("Error publishing log: %s", e)
    
    async def publish_alert(self, alert_type: str, severity: str, **kwargs):
        """
        Publish alert event for critical issues.
        
        Args:
            alert_type: Type of alert (e.g., 'collision', 'error', 'warning')
            severity: Severity level (e.g., 'critical', 'high', 'medium')
            **kwargs: Additional alert data
        """
        if not self.js:
            logger.warning("JetStream not available, skipping alert")
            return
        
        try:
            # Ensure stream exists for alert events
            stream_name = f"EVT_ALERT_{self.machine_id.replace('.', '_')}"
            await self._ensure_stream(self.evt_alert, stream_name)
            
            message = {
                'type': alert_type,
                'severity': severity,
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                **kwargs
            }
            await self.js.publish(
                self.evt_alert,
                json.dumps(message).encode()
            )
            logger.warning("Published alert (%s/%s): %s", alert_type, severity, self.evt_alert)
        except Exception as e:
            logger.error("Error publishing alert: %s", e)
    
    async def publish_media(self, media_url: str, media_type: str = "image", **kwargs):
        """
        Publish media event after uploading to object storage.
        
        Args:
            media_url: URL to the media in object storage
            media_type: Type of media (e.g., 'image', 'video')
            **kwargs: Additional media data
        """
        if not self.js:
            logger.warning("JetStream not available, skipping media")
            return
        
        try:
            # Ensure stream exists for media events
            stream_name = f"EVT_MEDIA_{self.machine_id.replace('.', '_')}"
            await self._ensure_stream(self.evt_media, stream_name)
            
            message = {
                'media_url': media_url,
                'media_type': media_type,
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                **kwargs
            }
            await self.js.publish(
                self.evt_media,
                json.dumps(message).encode()
            )
            logger.debug("Published media event: %s", self.evt_media)
        except Exception as e:
            logger.error("Error publishing media: %s", e)

