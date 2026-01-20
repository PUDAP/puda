"""
Example usage of the CommandService send_queue_commands method.

This file demonstrates how to use the send_queue_commands method to send
multiple commands sequentially in a single call. The method automatically
stops on the first error and returns the error response, or returns the
last successful response if all commands succeed.

The CommandService now supports:
- Async context manager for automatic connection/disconnection
- Automatic signal handlers (SIGTERM, SIGINT) for graceful shutdown
- Batch command sending with send_queue_commands()

Recommended usage: Use async context manager for automatic cleanup.
"""
import json
import uuid
import asyncio
import logging
from pathlib import Path
from puda_comms import CommandService
from puda_comms.models import CommandRequest, CommandResponseStatus, NATSMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Load commands from JSON file (useful when generating commands from LLM and loading from JSON)
COMMANDS_JSON_PATH = Path(__file__).parent / "commands.json"
TEST_RUN_ID = str(uuid.uuid4())
MACHINE_ID = "first"

def load_commands() -> list[dict]:
    """Load commands from JSON file."""
    with open(COMMANDS_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


async def main():
    """Run batch commands from JSON file."""
    logger.info("Starting batch command tests with run_id: %s", TEST_RUN_ID)
    
    async with CommandService() as service:
        # Load commands from JSON and convert to CommandRequest objects
        command_dicts = load_commands()
        requests = [CommandRequest(**cmd) for cmd in command_dicts]
        
        logger.info("Sending batch constructed from dicts (%d commands)...", len(requests))
        reply: NATSMessage = await service.send_queue_commands(
            requests=requests,
            machine_id=MACHINE_ID,
            run_id=TEST_RUN_ID
        )
        
        if reply is None:
            logger.error("Batch commands failed or timed out")
            return
        
        if reply.response and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Batch commands completed successfully!")
        else:
            logger.error("Batch commands failed")


if __name__ == "__main__":
    asyncio.run(main())