"""
Logger service that listens to NATS response streams
and logs command responses to PostgreSQL database.
"""
import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional
import nats
from nats.js.client import JetStreamContext
from nats.aio.msg import Msg
from puda_db import DatabaseClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
NATS_SERVERS = os.getenv(
    "NATS_SERVERS",
    "nats://localhost:4222"
).split(",")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "puda")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

# NATS stream names
STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"

# Subject patterns to subscribe to (all machines)
NAMESPACE = "puda"
RESPONSE_QUEUE_PATTERN = f"{NAMESPACE}.*.cmd.response.queue"
RESPONSE_IMMEDIATE_PATTERN = f"{NAMESPACE}.*.cmd.response.immediate"


class LoggerService:
    """Service that logs command responses to PostgreSQL."""
    
    def __init__(self):
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self.db_client = DatabaseClient(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        self._subscriptions = []
        self._is_connected = False
    
    async def connect_nats(self) -> bool:
        """Connect to NATS servers."""
        try:
            self.nc = await nats.connect(
                servers=NATS_SERVERS,
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback
            )
            self.js = self.nc.jetstream()
            self._is_connected = True
            logger.info("Connected to NATS servers: %s", NATS_SERVERS)
            return True
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", e)
            self._is_connected = False
            return False
    
    async def connect_db(self):
        """Connect to PostgreSQL database."""
        try:
            self.db_client.connect()
            logger.info("Connected to PostgreSQL database")
        except Exception as e:
            logger.error("Failed to connect to PostgreSQL: %s", e)
            raise
    
    async def _error_callback(self, error: Exception):
        """Callback for NATS errors."""
        logger.error("NATS error: %s", error)
    
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
            await self._subscribe_all()
    
    async def _closed_callback(self):
        """Callback when connection is closed."""
        logger.info("NATS connection closed")
        self._is_connected = False
    
    def _extract_machine_id(self, subject: str) -> Optional[str]:
        """Extract machine_id from NATS subject."""
        # Subject format: puda.{machine_id}.cmd.response.{type}
        try:
            parts = subject.split(".")
            if len(parts) >= 2:
                return parts[1]
        except Exception:
            pass
        return None
    
    def _parse_response(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Parse response message."""
        try:
            payload = json.loads(data.decode())
            header = payload.get('header', {})
            response = payload.get('response', {})
            return {
                'command': header.get('command', 'unknown'),
                'run_id': header.get('run_id'),
                'command_id': header.get('command_id', 'unknown'),
                'status': response.get('status'),
                'error': response.get('error'),
                'completed_at': response.get('completed_at'),
                'full_payload': payload
            }
        except Exception as e:
            logger.error("Error parsing response: %s", e)
            return None
    
    async def _handle_response(self, msg: Msg, response_type: str):
        """Handle incoming response message."""
        try:
            machine_id = self._extract_machine_id(msg.subject)
            response_data = self._parse_response(msg.data)
            
            if not response_data:
                await msg.ack()
                return
            
            # Insert response into database (connection is checked internally)
            self.db_client.insert_response_log(
                machine_id=machine_id or 'unknown',
                response_type=response_type,
                command=response_data['command'],
                run_id=response_data['run_id'],
                command_id=response_data['command_id'],
                status=response_data['status'],
                error=response_data.get('error'),
                completed_at=response_data.get('completed_at'),
                full_payload=response_data['full_payload']
            )
            
            logger.debug(
                "Logged response: machine_id=%s, command=%s, run_id=%s, command_id=%s, status=%s",
                machine_id, response_data['command'], response_data['run_id'],
                response_data['command_id'], response_data['status']
            )
            
            await msg.ack()
        except Exception as e:
            logger.error("Error handling response: %s", e, exc_info=True)
            # Try to reconnect to database if connection was lost
            try:
                self.db_client.connect()
            except Exception as db_error:
                logger.error("Failed to reconnect to database: %s", db_error)
            try:
                await msg.ack()  # Ack even on error to avoid redelivery loops
            except Exception:
                pass
    
    async def _subscribe_all(self):
        """Subscribe to all response streams."""
        if not self.js:
            logger.error("JetStream not available")
            return
        
        # Subscribe to response streams
        try:
            resp_queue_sub = await self.js.subscribe(
                RESPONSE_QUEUE_PATTERN,
                stream=STREAM_RESPONSE_QUEUE,
                durable="logger_resp_queue",
                cb=lambda msg: asyncio.create_task(
                    self._handle_response(msg, "queue")
                )
            )
            self._subscriptions.append(resp_queue_sub)
            logger.info("Subscribed to response queue: %s", RESPONSE_QUEUE_PATTERN)
        except Exception as e:
            logger.error("Failed to subscribe to response queue: %s", e)
        
        try:
            resp_immediate_sub = await self.js.subscribe(
                RESPONSE_IMMEDIATE_PATTERN,
                stream=STREAM_RESPONSE_IMMEDIATE,
                durable="logger_resp_immediate",
                cb=lambda msg: asyncio.create_task(
                    self._handle_response(msg, "immediate")
                )
            )
            self._subscriptions.append(resp_immediate_sub)
            logger.info("Subscribed to response immediate: %s", RESPONSE_IMMEDIATE_PATTERN)
        except Exception as e:
            logger.error("Failed to subscribe to response immediate: %s", e)
    
    async def disconnect(self):
        """Disconnect from NATS and close database connection."""
        # Unsubscribe from all streams
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()
        
        # Close NATS connection
        if self.nc:
            await self.nc.close()
        
        # Close database connection
        self.db_client.close()
        
        logger.info("Disconnected from NATS and PostgreSQL")
    
    async def run(self):
        """Run the logger service."""
        # Connect to database
        await self.connect_db()
        
        # Connect to NATS with retry logic
        while True:
            if await self.connect_nats():
                break
            logger.error("Failed to connect to NATS, retrying in 5 seconds...")
            await asyncio.sleep(5)
        
        # Subscribe to all streams
        await self._subscribe_all()
        
        logger.info("Logger service started and listening for command responses")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
                # Check connection health
                if not self._is_connected:
                    logger.warning("Connection lost, attempting to reconnect...")
                    if await self.connect_nats():
                        await self._subscribe_all()
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt, shutting down...")
        except Exception as e:
            logger.error("Unexpected error in main loop: %s", e, exc_info=True)
        finally:
            await self.disconnect()


async def main():
    """Main entry point."""
    service = LoggerService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())

