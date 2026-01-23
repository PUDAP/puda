"""
Example usage of the command service.

This file demonstrates how to use the CommandService to send commands to machines.

The commands are what the LLM should generate. 

The CommandService now supports:
- Async context manager for automatic connection/disconnection
- Automatic signal handlers (SIGTERM, SIGINT) for graceful shutdown
- Idempotent disconnect() method

Recommended usage: Use async context manager for automatic cleanup.
"""
import uuid
import asyncio
import logging
import os
from puda_comms import CommandService
from puda_comms.models import CommandRequest, CommandResponseStatus, NATSMessage, ImmediateCommand

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Test user credentials
USER_ID = str(uuid.uuid4())  # unique to user
USERNAME = "Test User"
MACHINE_ID = "first"
DEFAULT_NATS_SERVERS = "nats://100.86.162.126:4222,nats://100.86.162.126:4223,nats://100.86.162.126:4224"


def get_nats_servers() -> list[str]:
    """Get NATS servers from environment variable or use default."""
    nats_servers_env = os.getenv("NATS_SERVERS", DEFAULT_NATS_SERVERS)
    return [s.strip() for s in nats_servers_env.split(",")]


async def load_labware(run_id: str):
    """Example: Send a single command using context manager."""
    # Using async context manager - automatically connects and disconnects
    async with CommandService(servers=get_nats_servers()) as service:
        # Send a single command
        request = CommandRequest(
            name="load_labware",
            params={
                "slot": "A1",
                "labware_name": "opentrons_96_tiprack_300ul"
            },
            step_number=1
        )
        reply: NATSMessage = await service.send_queue_command(
            request=request, machine_id=MACHINE_ID, run_id=run_id, user_id=USER_ID, username=USERNAME
        )
        
        if reply is None:
            logger.error("Command failed or timed out")
            return
        
        if reply.response is not None and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Command completed successfully")
        

async def remove_labware(run_id: str):
    """Example: Send a single command using context manager."""
    # Using async context manager - automatically connects and disconnects
    async with CommandService(servers=get_nats_servers()) as service:
        # Remove the labware from the slot
        request = CommandRequest(
            name="remove_labware",
            params={
                "slot": "A1"
            },
            step_number=1
        )
        reply: NATSMessage = await service.send_queue_command(
            request=request, machine_id=MACHINE_ID, run_id=run_id, user_id=USER_ID, username=USERNAME
        )
        
        if reply is None:
            logger.error("Command failed or timed out")
            return
        
        if reply.response is not None and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Labware removed successfully")


async def example_command_sequence(run_id: str):
    """Example: Send a sequence of commands using context manager."""
    # Using async context manager - automatically connects and disconnects
    async with CommandService(servers=get_nats_servers()) as service:
        # Define command sequence
        commands = [
            {
                "name": "load_deck",
                "params": {
                    "deck_layout": {
                        "C1": "trash_bin",
                        "C2": "polyelectric_8_wellplate_30000ul",
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
                "name": "aspirate_from",
                "params": {"slot": "C2", "well": "A1", "amount": 100},
                "step_number": 3
            },
            {
                "name": "dispense_to",
                "params": {"slot": "C2", "well": "B4", "amount": 100},
                "step_number": 4
            },
            {
                "name": "drop_tip",
                "params": {"slot": "C1", "well": "A1"},
                "step_number": 5
            }
        ]
        
        # Send sequence using for loop
        all_succeeded = True
        for cmd in commands:
            # turn cmd into CommandRequest model
            request = CommandRequest(**cmd)
            reply: NATSMessage = await service.send_queue_command(
                request=request, machine_id=MACHINE_ID, run_id=run_id, user_id=USER_ID, username=USERNAME
            )
            
            if reply is None:
                logger.error("Command failed or timed out: %s (step %s)", request.name, request.step_number)
                all_succeeded = False
                break
            
            if reply.response is not None and reply.response.status != CommandResponseStatus.SUCCESS:
                all_succeeded = False
                break
            
            logger.info("Command succeeded: %s (step %s)", request.name, request.step_number)
        
        if all_succeeded:
            logger.info("All commands completed successfully")
        else:
            logger.error("Command sequence failed")
    

async def example_pause(run_id: str):
    """Example: Send pause command using context manager."""
    # Using async context manager - automatically connects and disconnects
    # Signal handlers are automatically registered for graceful shutdown
    async with CommandService(servers=get_nats_servers()) as service:
        pause_request = CommandRequest(
            name=ImmediateCommand.PAUSE,
            step_number=1
        )
        reply: NATSMessage = await service.send_immediate_command(
            request=pause_request, machine_id=MACHINE_ID, run_id=run_id, user_id=USER_ID, username=USERNAME
        )
        if reply is not None:
            logger.info("Pause command result: status=%s, message=%s", reply.response.status, reply.response.message)
        else:
            logger.error("Pause command failed or timed out")
    # Automatically disconnects here, even on exceptions or signals


async def example_resume(run_id: str):
    """Example: Send resume command using context manager."""
    # Using async context manager - automatically connects and disconnects
    # Signal handlers are automatically registered for graceful shutdown
    async with CommandService(servers=get_nats_servers()) as service:
        resume_request = CommandRequest(
            name=ImmediateCommand.RESUME,
            step_number=1
        )
        reply:NATSMessage = await service.send_immediate_command(
            request=resume_request, machine_id=MACHINE_ID, run_id=run_id, user_id=USER_ID, username=USERNAME
        )
        if reply:
            logger.info("Resume command result: status=%s, message=%s", reply.response.status, reply.response.message)
        else:
            logger.error("Resume command failed or timed out")
    # Automatically disconnects here, even on exceptions or signals


async def example_cancel(run_id: str):
    """Example: Send cancel command using context manager."""
    # Using async context manager - automatically connects and disconnects
    # Signal handlers are automatically registered for graceful shutdown
    async with CommandService(servers=get_nats_servers()) as service:
        cancel_request = CommandRequest(
            name=ImmediateCommand.CANCEL,
            step_number=1
        )
        reply = await service.send_immediate_command(
            request=cancel_request, machine_id=MACHINE_ID, run_id=run_id, user_id=USER_ID, username=USERNAME
        )
        if reply:
            logger.info("Cancel command result: status=%s, message=%s", reply.response.status, reply.response.message)
        else:
            logger.error("Cancel command failed or timed out")
    # Automatically disconnects here, even on exceptions or signals


async def example_get_deck(run_id: str):
    """Example: Get current deck layout using context manager."""
    # Using async context manager - automatically connects and disconnects
    async with CommandService(servers=get_nats_servers()) as service:
        request = CommandRequest(
            name="get_deck",
            step_number=1
        )
        reply: NATSMessage = await service.send_queue_command(
            request=request, machine_id=MACHINE_ID, run_id=run_id, user_id=USER_ID, username=USERNAME
        )
        
        if reply is None:
            logger.error("Get deck command failed or timed out")
            return
        
        if reply.response is not None and reply.response.status == CommandResponseStatus.SUCCESS:
            deck_data = reply.response.data
            if deck_data:
                logger.info("Current deck layout: %s", deck_data)
            else:
                logger.info("Get deck completed successfully (no deck data returned)")
    # Automatically disconnects here, even on exceptions or signals

if __name__ == "__main__":
    TEST_RUN_ID = str(uuid.uuid4())
    # Run examples
    asyncio.run(load_labware(TEST_RUN_ID))
    # asyncio.run(example_get_deck(TEST_RUN_ID))
    # asyncio.run(remove_labware(TEST_RUN_ID))
    # asyncio.run(example_get_deck(TEST_RUN_ID))

    # asyncio.run(example_command_sequence(TEST_RUN_ID))
    # asyncio.run(example_pause(TEST_RUN_ID))
    # asyncio.run(example_resume(TEST_RUN_ID))
    # asyncio.run(example_cancel(TEST_RUN_ID))