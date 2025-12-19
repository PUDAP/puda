"""
Test script to send commands to a machine via NATS
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
import nats

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

MACHINE_ID = "test-machine"
NAMESPACE = "puda"


async def send_execute_command(
    servers: list[str],
    machine_id: str,
    command: str,
    parameters: dict,
    run_id: str,
    command_id: str
):
    """
    Send an execute command to a machine.
    
    Args:
        servers: List of NATS server URLs
        machine_id: Machine identifier
        command: Command name (e.g., "aspirate_from")
        parameters: Command parameters
        run_id: Run ID for the experiment (should be same for all commands in experiment)
        command_id: Command ID (should increment for each command, starting at "0")
    """
    # Connect to NATS
    nc = await nats.connect(servers=servers)
    js = nc.jetstream()
    
    try:
        # Subject for execute commands
        subject = f"{NAMESPACE}.{machine_id}.cmd.execute"
        
        # Command payload in Envelope Pattern format
        payload = {
            'header': {
                'command': command,
                'version': '1.0',
                'run_id': run_id,
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            },
            'params': parameters
        }
        
        logger.info(f"Sending execute command to {subject}")
        logger.info(f"Run ID: {run_id}")
        logger.info(f"Command: {command}")
        logger.info(f"Parameters: {parameters}")
        
        # Publish to JetStream (execute commands use JetStream)
        ack = await js.publish(
            subject,
            json.dumps(payload).encode()
        )
        
        logger.info(f"Command sent successfully. Sequence: {ack.seq}")
        logger.info(f"Stream: {ack.stream}")
        
    except Exception as e:
        logger.error(f"Failed to send command: {e}")
        raise
    finally:
        await nc.close()


async def send_pause_command(
    servers: list[str],
    machine_id: str,
    run_id: str
):
    """
    Send a pause command to a machine.
    
    Args:
        servers: List of NATS server URLs
        machine_id: Machine identifier
        run_id: Run ID to pause
    """
    nc = await nats.connect(servers=servers)
    js = nc.jetstream()
    
    try:
        subject = f"{NAMESPACE}.{machine_id}.cmd.pause"
        
        # Command payload in Envelope Pattern format
        payload = {
            'header': {
                'command': 'pause',
                'version': '1.0',
                'run_id': run_id,
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            },
            'params': {}
        }
        
        logger.info(f"Sending pause command to {subject} for run_id: {run_id}")
        
        ack = await js.publish(
            subject,
            json.dumps(payload).encode()
        )
        
        logger.info(f"Pause command sent successfully. Sequence: {ack.seq}")
        
    except Exception as e:
        logger.error(f"Failed to send pause command: {e}")
        raise
    finally:
        await nc.close()


async def send_cancel_command(
    servers: list[str],
    machine_id: str,
    run_id: str
):
    """
    Send a cancel command to a machine.
    
    Args:
        servers: List of NATS server URLs
        machine_id: Machine identifier
        run_id: Run ID to cancel
    """
    nc = await nats.connect(servers=servers)
    js = nc.jetstream()
    
    try:
        subject = f"{NAMESPACE}.{machine_id}.cmd.cancel"
        
        # Command payload in Envelope Pattern format
        payload = {
            'header': {
                'command': 'cancel',
                'version': '1.0',
                'run_id': run_id,
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            },
            'params': {}
        }
        
        logger.info(f"Sending cancel command to {subject} for run_id: {run_id}")
        
        ack = await js.publish(
            subject,
            json.dumps(payload).encode()
        )
        
        logger.info(f"Cancel command sent successfully. Sequence: {ack.seq}")
        
    except Exception as e:
        logger.error(f"Failed to send cancel command: {e}")
        raise
    finally:
        await nc.close()


async def main():
    """Main function to send commands to machine"""
    servers = ["nats://localhost:4222", "nats://localhost:4223", "nats://localhost:4224"]
    
    # Generate run_id for this experiment (same for all commands in experiment)
    run_id = str(uuid.uuid4())
    
    # Command counter (starts at 0, increments for each command)
    command_id = 0
    
    logger.info("=" * 60)
    logger.info("Sending execute commands to machine")
    logger.info(f"Experiment Run ID: {run_id}")
    logger.info("=" * 60)
    
    try:
        # Example: Send first command
        command1 = "aspirate_from"
        parameters1 = {
            "slot": "A1",
            "well": "D2",
            "amount": 100
        }
        
        await send_execute_command(
            servers=servers,
            machine_id=MACHINE_ID,
            command=command1,
            parameters=parameters1,
            run_id=run_id,
            command_id=str(command_id)
        )
        command_id += 1
        
        # Example: Send second command (same run_id, incremented command_id)
        # Uncomment to test multiple commands:
        # await asyncio.sleep(1)
        # command2 = "calibrate_sensor"
        # parameters2 = {"voltage": 1.2}
        # await send_execute_command(
        #     servers=servers,
        #     machine_id=MACHINE_ID,
        #     command=command2,
        #     parameters=parameters2,
        #     run_id=run_id,
        #     command_id=str(command_id)
        # )
        # command_id += 1
        
        logger.info("=" * 60)
        logger.info(f"Commands sent successfully with run_id: {run_id}")
        logger.info("=" * 60)
        
        # Optionally, you can send pause or cancel commands:
        # Uncomment to test pause:
        # await asyncio.sleep(2)
        # await send_pause_command(servers, MACHINE_ID, run_id)
        
        # Uncomment to test cancel:
        # await asyncio.sleep(2)
        # await send_cancel_command(servers, MACHINE_ID, run_id)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

