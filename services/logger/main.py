"""
Logger service that listens to NATS response streams
and logs command responses to PostgreSQL database.
"""
import asyncio
import json
import logging
import os
from typing import Optional
from dotenv import load_dotenv
from nats.aio.msg import Msg
from puda_comms import StreamSubscriber
from puda_comms.models import NATSMessage
from puda_db import DatabaseClient

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

NATS_SERVERS = get_required_env("NATS_SERVERS").split(",")
POSTGRES_HOST = get_required_env("POSTGRES_HOST")
POSTGRES_PORT = int(get_required_env("POSTGRES_PORT"))
POSTGRES_DB = get_required_env("POSTGRES_DB")
POSTGRES_USER = get_required_env("POSTGRES_USER")
POSTGRES_PASSWORD = get_required_env("POSTGRES_PASSWORD")

# NATS stream names
STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"

# Subject patterns to subscribe to (all machines)
NAMESPACE = "puda"
RESPONSE_QUEUE_PATTERN = f"{NAMESPACE}.*.cmd.response.queue"
RESPONSE_IMMEDIATE_PATTERN = f"{NAMESPACE}.*.cmd.response.immediate"

class LoggerService(StreamSubscriber):
    """Service that logs command responses to PostgreSQL."""
    
    def __init__(self):
        # Initialize StreamSubscriber with NATS servers
        super().__init__(servers=NATS_SERVERS)
        
        # Initialize database client
        self.db_client = DatabaseClient(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        
        # Track subscription info for reconnection
        self._subscription_info = []
    
    async def connect_db(self):
        """Connect to PostgreSQL database."""
        try:
            self.db_client.connect()
            logger.info("Connected to PostgreSQL database")
        except Exception as e:
            logger.error("Failed to connect to PostgreSQL: %s", e)
            raise
    
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
    
    async def handle_message(self, msg: Msg, stream: str, subject: str):
        """
        Handle an incoming message from any subscribed stream.
        
        Determines response_type from stream name and delegates to _handle_response.
        """
        # Parse bytes to NATSMessage object
        try:
            message_data = msg.data.decode('utf-8')
            nats_message = NATSMessage.model_validate_json(message_data)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse message data: %s", e)
            await msg.ack()
            return

        # Determine response_type from stream name
        match stream:
            case x if x == STREAM_RESPONSE_QUEUE:
                command_type = "queue"
                self.db_client.insert_command_log(message=nats_message, command_type=command_type)
            case x if x == STREAM_RESPONSE_IMMEDIATE:
                command_type = "immediate"
                self.db_client.insert_command_log(message=nats_message, command_type=command_type)
            case _:
                command_type = "unknown"
                logger.error("Unknown stream: %s", stream)
        
        await msg.ack()

    
    async def on_start(self):
        """Set up subscriptions when the service starts."""
        # Subscribe to response streams
        await self.subscribe(
            STREAM_RESPONSE_QUEUE,
            RESPONSE_QUEUE_PATTERN,
            durable="logger_resp_queue"
        )
        self._subscription_info.append({
            'stream': STREAM_RESPONSE_QUEUE,
            'subject': RESPONSE_QUEUE_PATTERN,
            'durable': "logger_resp_queue"
        })
        
        await self.subscribe(
            STREAM_RESPONSE_IMMEDIATE,
            RESPONSE_IMMEDIATE_PATTERN,
            durable="logger_resp_immediate"
        )
        self._subscription_info.append({
            'stream': STREAM_RESPONSE_IMMEDIATE,
            'subject': RESPONSE_IMMEDIATE_PATTERN,
            'durable': "logger_resp_immediate"
        })
    
    async def _resubscribe_all(self):
        """Re-subscribe to all streams after reconnection."""
        for info in self._subscription_info:
            try:
                await self.subscribe(
                    info['stream'],
                    info['subject'],
                    durable=info['durable']
                )
            except Exception as e:
                logger.error(
                    "Failed to re-subscribe to stream=%s, subject=%s: %s",
                    info['stream'], info['subject'], e
                )
    
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

