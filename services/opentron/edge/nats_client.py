"""
NATS Client Wrapper
Handles all NATS communication patterns for robot edge devices
"""
import json
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime
import nats
from nats.js.api import KeyValue
from nats.js.client import JetStreamContext

logger = logging.getLogger(__name__)

class NATSClient:
    """
    NATS client wrapper for any edge devices.
    Handles Request/Reply, Pub/Sub, KV Store, and JetStream patterns.
    """
    
    def __init__(self, servers: list[str], device_id: str):
        """
        Initialize NATS client.
        
        Args:
            servers: List of NATS server URLs (e.g., ["nats://localhost:4222", ...])
            device_id: Device ID (e.g., "opentron_01")
        """
        self.servers = servers
        self.device_id = device_id
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self.kv: Optional[KeyValue] = None
        
        namespace = "puda"
        site = "bears"
        
        # Subject patterns based on NATS best practices
        self.heartbeat_subject = f"{namespace}.{site}.{device_id}.telemetry.heartbeat"
        self.status_subject = f"{namespace}.{site}.{device_id}.telemetry.status" # only used if kv store is not available
        self.execute_subject = f"{namespace}.{site}.{device_id}.cmd.execute"
        self.cancel_subject = f"{namespace}.{site}.{device_id}.cmd.cancel"
        self.log_subject = f"{namespace}.{site}.{device_id}.evt.log"
        
        # KV bucket name for status
        self.kv_bucket_name = "MACHINE_STATE"
        
        # Subscriptions
        self._subscriptions = []
    
    async def connect(self) -> bool:
        """Connect to NATS server"""
        try:
            self.nc = await nats.connect(servers=self.servers)
            self.js = self.nc.jetstream()
            
            # Create KV bucket for status if it doesn't exist
            try:
                self.kv = await self.js.create_key_value(
                    bucket=self.kv_bucket_name
                )
            except Exception as e:
                # Bucket might already exist, try to get it
                try:
                    self.kv = await self.js.key_value(self.kv_bucket_name)
                except Exception:
                    logger.warning("Could not create or access KV bucket: %s", e)
                    self.kv = None
            
            logger.info("Connected to NATS servers: %s", self.servers)
            return True
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", e)
            return False
    
    async def disconnect(self):
        """Disconnect from NATS server"""
        # Unsubscribe from all subscriptions
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        
        if self.nc:
            await self.nc.close()
            logger.info("Disconnected from NATS")
    
    async def subscribe_execute(
        self, 
        handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    ):
        """
        Subscribe to execute commands using Request/Reply pattern.
        
        Args:
            handler: Async function that takes protocol data and returns response
        """
        async def message_handler(msg):
            try:
                payload = json.loads(msg.data.decode())
                logger.info("Received execute command: %s", payload)
                
                # Call handler and get response
                response = await handler(payload)
                
                # Reply with response
                await msg.respond(json.dumps(response).encode())
                logger.info("Sent execute response: %s", response)
                
            except json.JSONDecodeError as e:
                logger.error("Failed to decode JSON: %s", e)
                await msg.respond(json.dumps({
                    'status': 'error',
                    'error': f'Invalid JSON: {e}'
                }).encode())
            except Exception as e:
                logger.error("Error handling execute command: %s", e)
                await msg.respond(json.dumps({
                    'status': 'error',
                    'error': str(e)
                }).encode())
        
        sub = await self.nc.subscribe(self.execute_subject, cb=message_handler)
        self._subscriptions.append(sub)
        logger.info("Subscribed to execute commands: %s", self.execute_subject)
    
    async def subscribe_cancel(
        self,
        handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    ):
        """
        Subscribe to cancel commands using Request/Reply pattern.
        
        Args:
            handler: Async function that takes cancel data and returns response
        """
        async def message_handler(msg):
            try:
                payload = json.loads(msg.data.decode())
                logger.info("Received cancel command: %s", payload)
                
                # Call handler and get response
                response = await handler(payload)
                
                # Reply with response
                await msg.respond(json.dumps(response).encode())
                logger.info("Sent cancel response: %s", response)
                
            except json.JSONDecodeError as e:
                logger.error("Failed to decode JSON: %s", e)
                await msg.respond(json.dumps({
                    'status': 'error',
                    'error': f'Invalid JSON: {e}'
                }).encode())
            except Exception as e:
                logger.error("Error handling cancel command: %s", e)
                await msg.respond(json.dumps({
                    'status': 'error',
                    'error': str(e)
                }).encode())
        
        sub = await self.nc.subscribe(self.cancel_subject, cb=message_handler)
        self._subscriptions.append(sub)
        logger.info("Subscribed to cancel commands: %s", self.cancel_subject)
    
    async def publish_heartbeat(self, data: Dict[str, Any]):
        """Publish heartbeat message"""
        try:
            message = {
                'device_id': self.device_id,
                'timestamp': datetime.now().isoformat(),
                **data
            }
            await self.nc.publish(
                self.heartbeat_subject,
                json.dumps(message).encode()
            )
            logger.debug("Published heartbeat: %s", self.heartbeat_subject)
        except Exception as e:
            logger.error("Error publishing heartbeat: %s", e)
    
    async def update_status_kv(self, status_data: Dict[str, Any]):
        """
        Update robot status in KV store.
        This is more efficient than pub/sub for status that changes infrequently.
        """
        if not self.kv:
            logger.warning("KV store not available, falling back to pub/sub")
            await self.publish_status(status_data)
            return
        
        try:
            message = {
                'device_id': self.device_id,
                'timestamp': datetime.now().isoformat(),
                **status_data
            }
            await self.kv.put(
                self.device_id,
                json.dumps(message).encode()
            )
            logger.debug("Updated status in KV store: %s", self.device_id)
        except Exception as e:
            logger.error("Error updating status KV: %s", e)
            # Fallback to pub/sub
            await self.publish_status(status_data)
    
    async def publish_status(self, status_data: Dict[str, Any]):
        """Publish status update (fallback if KV store unavailable)"""
        try:
            message = {
                'device_id': self.device_id,
                'timestamp': datetime.now().isoformat(),
                **status_data
            }
            await self.nc.publish(
                self.status_subject,
                json.dumps(message).encode()
            )
            logger.debug("Published status: %s", self.status_subject)
        except Exception as e:
            logger.error("Error publishing status: %s", e)
    
    async def publish_log(self, log_data: Dict[str, Any]):
        """
        Publish log/event message to JetStream.
        This persists events for later analysis.
        """
        if not self.js:
            logger.warning("JetStream not available, skipping log publish")
            return
        
        try:
            message = {
                'device_id': self.device_id,
                'timestamp': datetime.now().isoformat(),
                **log_data
            }
            await self.js.publish(
                self.log_subject,
                json.dumps(message).encode()
            )
            logger.debug("Published log: %s", self.log_subject)
        except Exception as e:
            logger.error("Error publishing log: %s", e)

