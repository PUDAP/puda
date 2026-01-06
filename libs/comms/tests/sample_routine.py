"""
Test script to send commands to a machine via NATS
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
import nats
from nats.js.client import JetStreamContext
from nats.errors import BadSubscriptionError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

MACHINE_ID = "first"
NAMESPACE = "puda"
KV_BUCKET_NAME = f"MACHINE_STATE_{MACHINE_ID.replace('.', '-')}"


async def read_status(js: JetStreamContext, machine_id: str) -> dict:
    """
    Read machine status from KV store.
    
    Args:
        js: JetStream context
        machine_id: Machine identifier
    
    Returns:
        Dictionary with status data or None if not found
    """
    try:
        kv = await js.key_value(KV_BUCKET_NAME)
        entry = await kv.get(machine_id)
        
        if entry:
            status = json.loads(entry.value.decode())
            return status
        else:
            return None
    except (KeyError, json.JSONDecodeError, AttributeError) as e:
        logger.debug("Error reading status from KV store: %s", e)
        return None
    except Exception as e:  # pylint: disable=broad-except
        logger.debug("Unexpected error reading status from KV store: %s", e)
        return None


class ResponseHandler:
    """
    Manages response message handling using pull consumers.
    Uses pull consumers to avoid workqueue stream uniqueness constraints.
    Routes responses to waiting commands based on run_id and command_id.
    """
    def __init__(self, js: JetStreamContext, machine_id: str):
        self.js = js
        self.machine_id = machine_id
        self._pending_responses: Dict[str, Dict[str, Any]] = {}
        self._queue_consumer = None
        self._initialized = False
    
    async def _delete_all_consumers_on_subject(self, stream_name: str):
        """
        Try to delete consumers that might conflict.
        This is a best-effort cleanup.
        """
        try:
            from nats.js.errors import NotFoundError
            
            # Try common consumer name patterns that might exist
            patterns = [
                f"response_queue_{self.machine_id}",
                f"response_immediate_{self.machine_id}",
                f"resp_q_{self.machine_id}",
                f"resp_i_{self.machine_id}",
            ]
            
            for pattern in patterns:
                try:
                    await self.js.delete_consumer(stream_name, pattern)
                    logger.info("Deleted consumer: %s on %s", pattern, stream_name)
                except NotFoundError:
                    pass
                except Exception as e:
                    logger.debug("Could not delete consumer %s: %s", pattern, e)
                    
        except Exception as e:
            logger.debug("Error deleting consumers: %s", e)
    
    async def initialize(self):
        """Initialize the response handler using pull consumers."""
        if self._initialized:
            return
        
        queue_subject = f"{NAMESPACE}.{self.machine_id}.cmd.response.queue"
        
        try:
            # Try to delete existing consumers that might conflict
            await self._delete_all_consumers_on_subject("RESPONSE_QUEUE")
            
            # Create ephemeral consumer (it'll be cleaned up automatically)
            # Note: If this fails, there's still a consumer we couldn't delete
            self._queue_consumer = await self.js.subscribe(
                queue_subject,
                stream="RESPONSE_QUEUE",
                cb=lambda msg: asyncio.create_task(self._handle_message(msg))
            )
            
            logger.info("Created consumer for queue response handling")
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Failed to initialize pull consumer: %s", error_msg)
            # Fallback: try to provide helpful error message
            if "filtered consumer not unique" in error_msg or "10100" in error_msg:
                logger.error(
                    "\n" + "=" * 80 +
                    "\nERROR: Cannot create consumer - another consumer already exists!\n"
                    f"Subject: {queue_subject}\n"
                    "Workqueue streams only allow ONE consumer per subject pattern.\n\n"
                    "SOLUTION: Delete existing consumers using NATS CLI:\n"
                    f"  nats consumer rm RESPONSE_QUEUE <consumer_name>\n\n"
                    "Or list consumers first:\n"
                    f"  nats consumer ls RESPONSE_QUEUE\n" +
                    "=" * 80
                )
            raise
        
        self._initialized = True
    
    async def _handle_message(self, msg):
        """Handle incoming response messages."""
        try:
            response = json.loads(msg.data.decode())
            
            # Extract run_id and command_id from header
            header = response.get('header', {})
            resp_run_id = header.get('run_id')
            resp_command_id = header.get('command_id')
            resp_command = header.get('command', 'unknown')
            
            # Extract response status from response.response.status
            response_data = response.get('response', {})
            status = response_data.get('status')
            
            # Look up pending response
            key = f"{resp_run_id}:{resp_command_id}"
            if key in self._pending_responses:
                pending = self._pending_responses[key]
                
                # Print response clearly
                print("\n" + "=" * 80)
                print("RESPONSE RECEIVED:")
                print(f"  Command: {resp_command}")
                print(f"  Command ID: {resp_command_id}")
                print(f"  Run ID: {resp_run_id}")
                print(f"  Status: {status.upper()}")
                
                if status == 'success':
                    print("  Result: SUCCESS")
                    pending['result']['result'] = True
                elif status == 'error':
                    error_msg = response_data.get('error', 'Unknown error')
                    print(f"  Result: ERROR - {error_msg}")
                    pending['result']['result'] = False
                
                print("\nFull Response:")
                print(json.dumps(response, indent=2))
                print("=" * 80 + "\n")
                
                # Signal that response was received
                pending['event'].set()
                del self._pending_responses[key]
            
            # Always acknowledge the message
            await msg.ack()
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.error("Error processing response message: %s", e)
            try:
                await msg.ack()
            except Exception:
                pass
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Unexpected error processing response message: %s", e)
            try:
                await msg.ack()
            except Exception:
                pass
    
    def register_pending(self, run_id: str, command_id: str) -> Tuple[asyncio.Event, Dict[str, Any]]:
        """
        Register a pending response and return event and result container.
        
        Returns:
            Tuple of (event, result_container)
        """
        key = f"{run_id}:{command_id}"
        event = asyncio.Event()
        result_container = {'result': None}
        self._pending_responses[key] = {
            'event': event,
            'result': result_container
        }
        return event, result_container
    
    async def cleanup(self):
        """Clean up subscriptions."""
        if self._queue_consumer:
            try:
                await self._queue_consumer.unsubscribe()
            except Exception:
                pass


async def setup_response_subscription(handler: ResponseHandler, run_id: str, command_id: str):
    """
    Register a pending response with the shared response handler.
    
    Args:
        handler: Shared ResponseHandler instance
        run_id: Run ID to wait for
        command_id: Command ID to wait for
    
    Returns:
        Tuple of (None, response_received_event, result_container_dict)
        Note: First element is None since we use shared handler
    """
    response_received, result_container = handler.register_pending(run_id, command_id)
    return None, response_received, result_container


async def wait_for_response_with_subscription(
    sub, response_received: asyncio.Event, result_container: dict, timeout: float = 60.0
) -> bool:
    """
    Wait for response using a pre-setup subscription.
    
    This should be used after setup_response_subscription() to avoid race conditions.
    
    Args:
        sub: NATS subscription (from setup_response_subscription) - can be None for shared handler
        response_received: Event that will be set when response arrives
        result_container: Dict with 'result' key that will contain the result
        timeout: Maximum time to wait in seconds
    
    Returns:
        True if success, False if error
    """
    logger.info("Waiting for response (timeout: %s)...", timeout)
    
    try:
        # Wait for response with timeout
        try:
            await asyncio.wait_for(response_received.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Timeout waiting for response after {timeout}s") from exc
        
        # Give a small delay to ensure any pending messages are processed
        await asyncio.sleep(0.1)
        
        # Return result
        return result_container['result']
    finally:
        # Only try to unsubscribe if sub is not None (shared handler uses None)
        if sub is not None:
            try:
                await sub.unsubscribe()
            except BadSubscriptionError:
                # Subscription might already be invalid (e.g., due to timeout cancellation)
                logger.debug("Subscription already invalid, skipping unsubscribe")
            except Exception as e:  # pylint: disable=broad-except
                # Other unexpected errors during unsubscribe
                logger.debug("Error during unsubscribe: %s", e)


async def send_execute_command(
    js: JetStreamContext,
    handler: ResponseHandler,
    machine_id: str,
    payload: dict,
    run_id: str,
    command_id: str
):
    """
    Send an execute command to a machine and wait for acknowledgment.
    
    Args:
        js: JetStream context (for publishing commands)
        handler: Shared ResponseHandler instance
        machine_id: Machine identifier
        payload: Hardcoded command payload
        run_id: Run ID for the experiment
        command_id: Command ID
    
    Returns:
        True on ack (success), False on nak/term (error)
    """
    subject = f"{NAMESPACE}.{machine_id}.cmd.queue"
    
    # Register pending response BEFORE publishing to avoid race condition
    sub, response_received, result_container = await setup_response_subscription(
        handler, run_id, command_id
    )
    
    try:
        # Print command being sent
        command_name = payload.get('header', {}).get('command', 'unknown')
        print("\n" + "=" * 80)
        print("SENDING COMMAND:")
        print(f"  Command: {command_name}")
        print(f"  Command ID: {command_id}")
        print(f"  Run ID: {run_id}")
        print("\nFull Payload:")
        print(json.dumps(payload, indent=2))
        print("=" * 80)
        
        # Publish to JetStream (execute commands use JetStream)
        pub_ack = await js.publish(
            subject,
            json.dumps(payload).encode()
        )
        
        logger.info("Command sent successfully. Sequence: %s", pub_ack.seq)
        print(f"Command published (sequence: {pub_ack.seq}), waiting for response...\n")
        
        # Wait for response message
        try:
            result = await wait_for_response_with_subscription(
                sub, response_received, result_container, timeout=120.0
            )
            return result
        except TimeoutError as e:
            print(f"\n❌ TIMEOUT: {e}\n")
            logger.error("Timeout waiting for response: %s", e)
            return False
    except Exception:  # pylint: disable=broad-except
        # Cleanup is handled by shared handler, no need to unsubscribe here
        raise
    

async def send_pause_command(
    js: JetStreamContext,
    handler: ResponseHandler,
    machine_id: str,
    payload: dict,
    run_id: str
):
    """
    Send a pause command to a machine and wait for acknowledgment.
    
    Args:
        js: JetStream context (for publishing commands)
        handler: Shared ResponseHandler instance
        machine_id: Machine identifier
        payload: Hardcoded pause command payload
        run_id: Run ID to pause
    
    Returns:
        True on ack (success), False on nak/term (error)
    """
    subject = f"{NAMESPACE}.{machine_id}.cmd.immediate"
    command_id = payload.get('header', {}).get('command_id', 'pause')
    
    # Register pending response BEFORE publishing to avoid race condition
    sub, response_received, result_container = await setup_response_subscription(
        handler, run_id, command_id
    )
    
    try:
        logger.info("Sending pause command to %s for run_id: %s", subject, run_id)
        
        pub_ack = await js.publish(
            subject,
            json.dumps(payload).encode()
        )
        
        logger.info("Pause command sent successfully. Sequence: %s", pub_ack.seq)
        
        # Wait for response message
        try:
            result = await wait_for_response_with_subscription(
                sub, response_received, result_container, timeout=30.0
            )
            return result
        except TimeoutError as e:
            logger.error("Timeout waiting for pause response: %s", e)
            return False
    except Exception:  # pylint: disable=broad-except
        # Cleanup is handled by shared handler, no need to unsubscribe here
        raise


async def send_cancel_command(
    js: JetStreamContext,
    handler: ResponseHandler,
    machine_id: str,
    payload: dict,
    run_id: str
):
    """
    Send a cancel command to a machine and wait for acknowledgment.
    
    Args:
        js: JetStream context (for publishing commands)
        handler: Shared ResponseHandler instance
        machine_id: Machine identifier
        payload: Hardcoded cancel command payload
        run_id: Run ID to cancel
    
    Returns:
        True on ack (success), False on nak/term (error)
    """
    subject = f"{NAMESPACE}.{machine_id}.cmd.immediate"
    command_id = payload.get('header', {}).get('command_id', 'cancel')
    
    # Register pending response BEFORE publishing to avoid race condition
    sub, response_received, result_container = await setup_response_subscription(
        handler, run_id, command_id
    )
    
    try:
        logger.info("Sending cancel command to %s for run_id: %s", subject, run_id)
        
        pub_ack = await js.publish(
            subject,
            json.dumps(payload).encode()
        )
        
        logger.info("Cancel command sent successfully. Sequence: %s", pub_ack.seq)
        
        # Wait for response message
        try:
            result = await wait_for_response_with_subscription(
                sub, response_received, result_container, timeout=30.0
            )
            return result
        except TimeoutError as e:
            logger.error("Timeout waiting for cancel response: %s", e)
            return False
    except Exception:  # pylint: disable=broad-except
        # Cleanup is handled by shared handler, no need to unsubscribe here
        raise


async def main():
    """
    Main function to send commands to First machine.
    
    Commands are sent sequentially from the generated_sequence array,
    waiting for ACK before sending the next.
    Terminates on NAK/TERM (error state).
    """
    servers = ["nats://192.168.50.201:4222", "nats://192.168.50.201:4223", "nats://192.168.50.201:4224"]
    
    # Assume 'generated_sequence' comes from your MCP/LLM
    generated_sequence = [
        {
            "command": "load_deck",
            "params": {
                "deck_layout": { 
                    "C1": "trash_bin",
                    "C2": "polyelectric_8_wellplate_30000ul",
                    "A3": "opentrons_96_tiprack_300ul"
                }
            }
        },
        {
            "command": "attach_tip",
            "params": { "slot": "A3", "well": "G8" }
        },
        {
            "command": "aspirate_from",
            "params": { "slot": "C2", "well": "A1", "amount": 100 }
        },
        {
            "command": "dispense_to",
            "params": { "slot": "C2", "well": "B4", "amount": 100 }
        },
        {
            "command": "drop_tip",
            "params": { "slot": "C1", "well": "A1" }
        }
    ]
    
    # Generate run_id for this experiment (same for all commands in experiment)
    run_id = str(uuid.uuid4())
    
    # Command counter (starts at 0, increments for each command)
    command_id = 0
    
    print("\n" + "=" * 80)
    print("SENDING COMMANDS TO MACHINE")
    print(f"Machine ID: {MACHINE_ID}")
    print(f"Experiment Run ID: {run_id}")
    print(f"Total Commands: {len(generated_sequence)}")
    print("=" * 80 + "\n")
    
    # Connect to NATS and keep connection open
    nc = None
    handler = None
    try:
        nc = await nats.connect(servers=servers)
        js = nc.jetstream()
        logger.info("Connected to NATS")
        
        # Initialize shared response handler with durable consumers
        handler = ResponseHandler(js, MACHINE_ID)
        await handler.initialize()
        
        for step in generated_sequence:
            command_id += 1
            
            # 1. Construct the full payload dynamically
            full_payload = {
                'header': {
                    'command': step['command'],
                    'version': '1.0',
                    'run_id': run_id,
                    'command_id': str(command_id),
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                'params': step['params']
            }

            # 2. Execute command and wait for response
            print(f"\n[{command_id}/{len(generated_sequence)}] Processing command: {step['command']}")
            result = await send_execute_command(js, handler, MACHINE_ID, full_payload, run_id, str(command_id))
            
            if not result:
                error_msg = f"Command '{step['command']}' failed. Terminating."
                print(f"\n❌ ERROR: {error_msg}\n")
                raise RuntimeError(error_msg)
            else:
                print(f"✅ Command '{step['command']}' completed successfully\n")
        
        print("\n" + "=" * 80)
        print("✅ ALL COMMANDS COMPLETED SUCCESSFULLY")
        print(f"Run ID: {run_id}")
        print(f"Total Commands Executed: {command_id}")
        print("=" * 80 + "\n")
        
    except Exception as e:  # pylint: disable=broad-except
        logger.error(e, exc_info=True)
        return 1
    finally:
        if handler:
            await handler.cleanup()
        if nc:
            await nc.close()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

