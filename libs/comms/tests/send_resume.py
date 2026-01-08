"""
Script to send resume command to a machine via NATS
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
import nats
from nats.js.client import JetStreamContext
import uuid
from shared_response_handler import get_shared_handler, wait_for_response

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

MACHINE_ID = "first"
NAMESPACE = "puda"


async def send_resume_command(
    js: JetStreamContext,
    handler,
    machine_id: str,
    run_id: str,
    command_id: str = "resume"
):
    """
    Send a resume command to a machine and wait for acknowledgment.
    
    Args:
        js: JetStream context (for publishing commands)
        handler: Shared ResponseHandler instance
        machine_id: Machine identifier
        run_id: Run ID to resume (optional, can be None)
        command_id: Command ID (default: 'resume')
    
    Returns:
        True on ack (success), False on nak/term (error)
    """
    subject = f"{NAMESPACE}.{machine_id}.cmd.immediate"
    
    # Construct resume command payload
    payload = {
        'header': {
            'command': 'resume',
            'version': '1.0',
            'run_id': run_id,
            'command_id': command_id,
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        },
        'params': {}
    }
    
    logger.info("Sending resume command to %s for run_id: %s", subject, run_id)
    logger.info("Payload: \n%s", json.dumps(payload, indent=2))
    
    pub_ack = await js.publish(
        subject,
        json.dumps(payload).encode()
    )
    
    logger.info("Resume command sent successfully. Sequence: %s", pub_ack.seq)
    
    # Wait for response message using shared handler
    try:
        result = await wait_for_response(handler, run_id, command_id, timeout=30.0)
        return result
    except TimeoutError as e:
        logger.error("Timeout waiting for resume response: %s", e)
        return False


async def main():
    """
    Main function to send a resume command to a machine.
    """
    import sys
    
    # Parse command line arguments
    run_id = None
    if len(sys.argv) > 1:
        run_id = sys.argv[1]
    else:
        # Generate a run_id if not provided
        run_id = str(uuid.uuid4())
        logger.info("No run_id provided, using generated run_id: %s", run_id)
    
    servers = ["nats://192.168.50.201:4222", "nats://192.168.50.201:4223", "nats://192.168.50.201:4224"]
    command_id = "resume"
    
    logger.info("=" * 60)
    logger.info("Sending resume command to machine: %s", MACHINE_ID)
    logger.info("Run ID: %s", run_id)
    logger.info("=" * 60)
    
    # Connect to NATS
    nc = None
    handler = None
    try:
        nc = await nats.connect(servers=servers)
        js = nc.jetstream()
        logger.info("Connected to NATS")
        
        # Initialize shared response handler
        handler = get_shared_handler(js, MACHINE_ID)
        await handler.initialize()
        
        # Send resume command
        result = await send_resume_command(js, handler, MACHINE_ID, run_id, command_id)
        
        if result:
            logger.info("=" * 60)
            logger.info("Resume command completed successfully")
            logger.info("=" * 60)
            return 0
        else:
            logger.error("=" * 60)
            logger.error("Resume command failed")
            logger.error("=" * 60)
            return 1
        
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return 1
    finally:
        if handler:
            await handler.cleanup()
        if nc:
            await nc.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

