"""
Test script to send commands to a machine via NATS
"""
import asyncio
import json
import logging
import uuid
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




async def send_execute_command(
    js: JetStreamContext,
    handler,
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
    
    # Wait for response message using shared handler
    try:
        result = await wait_for_response(handler, run_id, command_id, timeout=120.0)
        return result
    except TimeoutError as e:
        print(f"\n❌ TIMEOUT: {e}\n")
        logger.error("Timeout waiting for response: %s", e)
        return False
    

async def send_pause_command(
    js: JetStreamContext,
    handler,
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
    
    logger.info("Sending pause command to %s for run_id: %s", subject, run_id)
    
    pub_ack = await js.publish(
        subject,
        json.dumps(payload).encode()
    )
    
    logger.info("Pause command sent successfully. Sequence: %s", pub_ack.seq)
    
    # Wait for response message using shared handler
    try:
        result = await wait_for_response(handler, run_id, command_id, timeout=30.0)
        return result
    except TimeoutError as e:
        logger.error("Timeout waiting for pause response: %s", e)
        return False


async def send_cancel_command(
    js: JetStreamContext,
    handler,
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
    
    logger.info("Sending cancel command to %s for run_id: %s", subject, run_id)
    
    pub_ack = await js.publish(
        subject,
        json.dumps(payload).encode()
    )
    
    logger.info("Cancel command sent successfully. Sequence: %s", pub_ack.seq)
    
    # Wait for response message using shared handler
    try:
        result = await wait_for_response(handler, run_id, command_id, timeout=30.0)
        return result
    except TimeoutError as e:
        logger.error("Timeout waiting for cancel response: %s", e)
        return False


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
        
        # Initialize shared response handler
        handler = get_shared_handler(js, MACHINE_ID)
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

