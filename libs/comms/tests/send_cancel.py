"""
Script to send cancel command to a machine via NATS
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
import nats
from nats.js.client import JetStreamContext
from shared_response_handler import get_shared_handler, wait_for_response

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

MACHINE_ID = "first"
NAMESPACE = "puda"


async def send_cancel_command(
    js: JetStreamContext,
    handler,
    machine_id: str,
    run_id: str,
    command_id: str = "cancel",
    timeout: float = 30.0
):
    """
    Send a cancel command to a machine using JetStream and wait for response.
    
    Args:
        js: JetStream context (for publishing commands)
        handler: Shared ResponseHandler instance
        machine_id: Machine identifier
        run_id: Run ID to cancel
        command_id: Command ID (default: 'cancel')
        timeout: Maximum time to wait for response in seconds
    
    Returns:
        True on success, False on error
    """
    subject = f"{NAMESPACE}.{machine_id}.cmd.immediate"
    
    # Construct cancel command payload
    payload = {
        'header': {
            'command': 'cancel',
            'version': '1.0',
            'run_id': run_id,
            'command_id': command_id,
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        },
        'params': {}
    }
    
    logger.info("Sending cancel command to %s for run_id: %s", subject, run_id)
    logger.info("Payload: \n%s", json.dumps(payload, indent=2))
    
    # Publish to JetStream
    pub_ack = await js.publish(
        subject,
        json.dumps(payload).encode()
    )
    
    logger.info("Cancel command sent successfully. Sequence: %s", pub_ack.seq)
    
    # Wait for response using shared handler
    try:
        result = await wait_for_response(handler, run_id, command_id, timeout=timeout)
        return result
    except TimeoutError:
        logger.error("Timeout waiting for cancel response after %s seconds", timeout)
        return False


async def main():
    """
    Main function to send a cancel command to a machine.
    """
    import sys
    
    # Parse command line arguments
    run_id = None
    if len(sys.argv) > 1:
        run_id = sys.argv[1]
    else:
        logger.error("Error: run_id is required for cancel command")
        logger.error("Usage: python send_cancel.py <run_id>")
        return 1
    
    servers = ["nats://192.168.50.201:4222", "nats://192.168.50.201:4223", "nats://192.168.50.201:4224"]
    command_id = "cancel"
    
    logger.info("=" * 60)
    logger.info("Sending cancel command to machine: %s", MACHINE_ID)
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
        
        # Send cancel command using shared handler
        result = await send_cancel_command(js, handler, MACHINE_ID, run_id, command_id)
        
        if result:
            logger.info("=" * 60)
            logger.info("Cancel command completed successfully")
            logger.info("=" * 60)
            return 0
        else:
            logger.error("=" * 60)
            logger.error("Cancel command failed")
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

