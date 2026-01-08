"""
Script to send resume command to a machine via NATS
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
import nats
from nats.js.client import JetStreamContext
from nats.errors import BadSubscriptionError
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

MACHINE_ID = "first"
NAMESPACE = "puda"


async def wait_for_response(js: JetStreamContext, machine_id: str, run_id: str, command_id: str, timeout: float = 60.0) -> bool:
    """
    Wait for command response by subscribing to JetStream response stream.
    
    Returns True on success, False on error.
    Raises TimeoutError if timeout is reached.
    
    Args:
        js: JetStream context (for subscribing to response stream)
        machine_id: Machine identifier
        run_id: Run ID to wait for
        command_id: Command ID to wait for
        timeout: Maximum time to wait in seconds
    
    Returns:
        True if success, False if error
    """
    response_subject = f"{NAMESPACE}.{machine_id}.cmd.response.immediate"
    stream_name = "RESPONSE_IMMEDIATE"
    response_received = asyncio.Event()
    result = None
    
    async def message_handler(msg):
        """Handle response messages from JetStream."""
        nonlocal result
        try:
            response = json.loads(msg.data.decode())
            
            logger.info("Response: \n%s", json.dumps(response, indent=2))
            
            # Extract run_id and command_id from header
            header = response.get('header', {})
            resp_run_id = header.get('run_id')
            resp_command_id = header.get('command_id')
            
            # Extract response status from response.result.status
            response_data = response.get('result', {})
            status = response_data.get('status')
            
            # Check if this response matches our command
            if resp_run_id == run_id and resp_command_id == command_id:
                if status == 'success':
                    logger.info("Received response: Command %s completed successfully", command_id)
                    result = True
                elif status == 'error':
                    error_msg = response_data.get('error', 'Unknown error')
                    logger.error("Received response: Command %s failed - %s", command_id, error_msg)
                    result = False
                response_received.set()
            
            # Always acknowledge the message to remove it from the stream
            await msg.ack()
        except Exception as e:
            logger.error("Error processing response message: %s", e)
            # Acknowledge even on error to prevent infinite retries
            try:
                await msg.ack()
            except Exception:
                pass
    
    # Subscribe to JetStream response stream
    sub = await js.subscribe(
        response_subject,
        stream=stream_name,
        cb=message_handler
    )
    logger.info("Waiting for response (run_id: %s, command_id: %s)...", run_id, command_id)
    
    try:
        # Wait for response with timeout
        try:
            await asyncio.wait_for(response_received.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for response after {timeout}s")
        
        # Return result
        return result
    finally:
        # Always try to unsubscribe, but handle if subscription is already invalid
        try:
            await sub.unsubscribe()
        except BadSubscriptionError:
            # Subscription might already be invalid (e.g., due to timeout cancellation)
            logger.debug("Subscription already invalid, skipping unsubscribe")
        except Exception as e:
            # Other unexpected errors during unsubscribe
            logger.debug("Error during unsubscribe: %s", e)


async def send_resume_command(
    js: JetStreamContext,
    machine_id: str,
    run_id: str,
    command_id: str = "resume"
):
    """
    Send a resume command to a machine and wait for acknowledgment.
    
    Args:
        js: JetStream context (for publishing commands and subscribing to responses)
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
    
    # Wait for response message from JetStream response stream
    try:
        result = await wait_for_response(js, machine_id, run_id, command_id, timeout=30.0)
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
    try:
        nc = await nats.connect(servers=servers)
        js = nc.jetstream()
        logger.info("Connected to NATS")
        
        # Send resume command
        result = await send_resume_command(js, MACHINE_ID, run_id, command_id)
        
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
        if nc:
            await nc.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

