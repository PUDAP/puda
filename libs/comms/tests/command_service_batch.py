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
import uuid
import asyncio
import logging
from puda_comms import CommandService
from puda_comms.models import CommandRequest, CommandResponseStatus, NATSMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def example_batch_command_sequence(run_id: str):
    """
    Example: Send a batch of commands using send_queue_commands.
    
    This demonstrates the new batch command functionality that sends
    all commands sequentially and automatically handles errors.
    """
    async with CommandService() as service:
        machine_id = "first"
        
        # Define command sequence as CommandRequest objects
        requests = [
            CommandRequest(
                name="load_deck",
                params={
                    "deck_layout": {
                        "C1": "trash_bin",
                        "C2": "polyelectric_8_wellplate_30000ul",
                        "A3": "opentrons_96_tiprack_300ul"
                    }
                },
                step_number=1
            ),
            CommandRequest(
                name="attach_tip",
                params={"slot": "A3", "well": "G8"},
                step_number=2
            ),
            CommandRequest(
                name="aspirate_from",
                params={"slot": "C2", "well": "A1", "amount": 100},
                step_number=3
            ),
            CommandRequest(
                name="dispense_to",
                params={"slot": "C2", "well": "B4", "amount": 100},
                step_number=4
            ),
            CommandRequest(
                name="drop_tip",
                params={"slot": "C1", "well": "A1"},
                step_number=5
            )
        ]
        
        # Send all commands in one batch call
        logger.info("Sending batch of %d commands...", len(requests))
        reply: NATSMessage = await service.send_queue_commands(
            requests=requests,
            machine_id=machine_id,
            run_id=run_id,
            timeout=120
        )
        
        # Check result
        if reply is None:
            logger.error("Batch command sequence failed or timed out")
            return False
        
        if reply.response is not None:
            if reply.response.status == CommandResponseStatus.SUCCESS:
                logger.info(
                    "All commands completed successfully! Last command: %s (step %s)",
                    reply.command.name if reply.command else "unknown",
                    reply.command.step_number if reply.command else "unknown"
                )
                return True
            else:
                logger.error(
                    "Batch command sequence failed with error: code=%s, message=%s",
                    reply.response.code,
                    reply.response.message
                )
                logger.error(
                    "Failed at command: %s (step %s)",
                    reply.command.name if reply.command else "unknown",
                    reply.command.step_number if reply.command else "unknown"
                )
                return False
        else:
            logger.warning("Batch command returned response with no response data")
            return False


async def example_batch_with_dict_construction(run_id: str):
    """
    Example: Construct commands from dictionaries and send as batch.
    
    Shows how to build CommandRequest objects from dict data.
    """
    async with CommandService() as service:
        machine_id = "first"
        
        # Define commands as dictionaries (useful when loading from JSON/config)
        command_dicts = [
            {
                "name": "load_deck",
                "params": {
                    "deck_layout": {
                        "C1": "trash_bin",
                        "A3": "opentrons_96_tiprack_300ul"
                    }
                },
                "step_number": 1
            },
            {
                "name": "attach_tip",
                "params": {"slot": "A3", "well": "G8"},
                "step_number": 2
            },
            {
                "name": "drop_tip",
                "params": {"slot": "C1", "well": "A1"},
                "step_number": 3
            }
        ]
        
        # Convert dicts to CommandRequest objects
        requests = [CommandRequest(**cmd) for cmd in command_dicts]
        
        logger.info("Sending batch constructed from dicts (%d commands)...", len(requests))
        reply: NATSMessage = await service.send_queue_commands(
            requests=requests,
            machine_id=machine_id,
            run_id=run_id
        )
        
        if reply is None:
            logger.error("Dict-based batch failed or timed out")
            return False
        
        if reply.response and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Dict-based batch completed successfully!")
            return True
        else:
            logger.error("Dict-based batch failed")
            return False


if __name__ == "__main__":
    TEST_RUN_ID = str(uuid.uuid4())
    logger.info("Starting batch command tests with run_id: %s", TEST_RUN_ID)
    
    # Run examples (uncomment the one you want to test)
    asyncio.run(example_batch_command_sequence(TEST_RUN_ID))
    # asyncio.run(example_batch_with_dict_construction(TEST_RUN_ID))

