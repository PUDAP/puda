"""
Script to send cancel command to a machine via NATS
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
import nats
from nats.js.client import JetStreamContext

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
    machine_id: str,
    run_id: str,
    command_id: str = "cancel",
    timeout: float = 30.0
):
    """
    Send a cancel command to a machine using JetStream and wait for response from JetStream response stream.
    
    Args:
        js: JetStream context (for publishing commands and subscribing to responses)
        nc: NATS connection
        machine_id: Machine identifier
        run_id: Run ID to cancel
        command_id: Command ID (default: 'cancel')
        timeout: Maximum time to wait for response in seconds
    
    Returns:
        True on success, False on error
    """
    subject = f"{NAMESPACE}.{machine_id}.cmd.immediate"
    response_subject = f"{NAMESPACE}.{machine_id}.cmd.response.immediate"
    stream_name = "RESPONSE_IMMEDIATE"
    
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
    
    response_received = asyncio.Event()
    result_container = {'result': None, 'response': None}
    
    async def response_handler(msg):
        """Handle response from JetStream response stream."""
        try:
            response = json.loads(msg.data.decode())
            logger.info("Response: \n%s", json.dumps(response, indent=2))
            
            # Extract run_id and command_id from header
            header = response.get('header', {})
            resp_run_id = header.get('run_id')
            resp_command_id = header.get('command_id')
            
            # Extract response status
            response_data = response.get('response', {})
            status = response_data.get('status')
            
            # Check if this response matches our command
            if resp_run_id == run_id and resp_command_id == command_id:
                result_container['response'] = response
                if status == 'success':
                    result_container['result'] = True
                elif status == 'error':
                    error_msg = response_data.get('error', 'Unknown error')
                    logger.error("Cancel command failed - %s", error_msg)
                    result_container['result'] = False
                else:
                    logger.warning("Unknown response status: %s", status)
                    result_container['result'] = False
                
                response_received.set()
            
            # Always acknowledge the message to remove it from the stream
            await msg.ack()
        except Exception as e:
            logger.error("Error processing response: %s", e)
            # Acknowledge even on error to prevent infinite retries
            try:
                await msg.ack()
            except Exception:
                pass
    
    # Try to delete existing consumers that might conflict
    # Workqueue streams only allow one consumer per subject pattern
    try:
        from nats.js.errors import NotFoundError
        
        # Try common consumer name patterns that might exist
        patterns = [
            f"response_immediate_{machine_id}",
            f"resp_i_{machine_id}",
            f"pull_resp_i_{machine_id}",
        ]
        
        for pattern in patterns:
            try:
                await js.delete_consumer(stream_name, pattern)
                logger.debug("Deleted existing consumer: %s on %s", pattern, stream_name)
            except NotFoundError:
                pass
            except Exception as e:
                logger.debug("Could not delete consumer %s: %s", pattern, e)
    except Exception as e:
        logger.debug("Error during consumer cleanup: %s", e)
    
    # Subscribe to JetStream response stream BEFORE publishing to avoid race condition
    try:
        sub = await js.subscribe(
            response_subject,
            stream=stream_name,
            cb=response_handler
        )
    except Exception as e:
        error_msg = str(e)
        if "filtered consumer not unique" in error_msg or "10100" in error_msg:
            logger.error(
                "\n" + "=" * 80 +
                "\nERROR: Cannot create consumer - another consumer already exists!\n"
                f"Subject: {response_subject}\n"
                "Workqueue streams only allow ONE consumer per subject pattern.\n\n"
                "SOLUTION: Delete existing consumers using NATS CLI:\n"
                f"  nats consumer rm {stream_name} <consumer_name>\n\n"
                "Or list consumers first:\n"
                f"  nats consumer ls {stream_name}\n" +
                "=" * 80
            )
        raise
    
    try:
        # Publish to JetStream (no reply subject)
        pub_ack = await js.publish(
            subject,
            json.dumps(payload).encode()
        )
        
        logger.info("Cancel command sent successfully. Sequence: %s", pub_ack.seq)
        
        # Wait for response with timeout
        try:
            await asyncio.wait_for(response_received.wait(), timeout=timeout)
            return result_container['result']
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for cancel response after %s seconds", timeout)
            return False
            
    except Exception as e:
        logger.error("Error sending cancel command: %s", e, exc_info=True)
        return False
    finally:
        # Clean up subscription
        try:
            await sub.unsubscribe()
        except Exception as e:
            logger.debug("Error unsubscribing from response stream: %s", e)


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
    try:
        nc = await nats.connect(servers=servers)
        js = nc.jetstream()
        logger.info("Connected to NATS")
        
        # Send cancel command using JetStream with response stream
        result = await send_cancel_command(js, MACHINE_ID, run_id, command_id)
        
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
        if nc:
            await nc.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

