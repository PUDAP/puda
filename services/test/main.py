"""
Example usage of MachineNATSClient
"""
import asyncio
import logging
from nats_client import MachineNATSClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

MACHINE_ID = "test-machine"


async def handle_execute_command(payload: dict) -> bool:
    """
    Handle execute command.
    
    Args:
        payload: JSON dictionary with envelope pattern (header, params)
    
    Returns:
        True if command executed successfully, False on error
        Raises exception on unexpected errors
    """
    run_id = payload['header']['run_id']
    
    print(f"Executing command with run_id: {run_id}")
    print(f"Command: {payload['header']['command']}")
    print(f"Params: {payload['params']}")
    
    # Your command execution logic here
    # Call your machine control methods here
    # ...
    
    # Example: Call machine control method
    # success = await machine.control_method(payload['header']['command'], payload['params'])
    
    # For now, simulate success with async sleep (non-blocking)
    await asyncio.sleep(10)
    success = True
    
    if success:
        print("Command executed successfully")
        return True
    else:
        print("Command execution failed")
        return False


async def handle_pause_command(payload: dict) -> bool:
    """
    Handle pause command.
    
    Args:
        payload: JSON dictionary with envelope pattern (header, params)
    
    Returns:
        True if command executed successfully, False on error
        Raises exception on unexpected errors
    """
    run_id = payload['header']['run_id']
    
    print(f"Pausing command with run_id: {run_id}")
    print(f"Command: {payload['header']['command']}")
    print(f"Params: {payload['params']}")
    
    # Your pause logic here
    # Call your machine control methods here
    # ...
    
    # Example: Call machine pause method
    # success = await machine.pause(run_id)
    
    # For now, simulate success
    success = True
    
    if success:
        print("Pause command executed successfully")
        return True
    else:
        print("Pause command failed")
        return False


async def handle_cancel_command(payload: dict) -> bool:
    """
    Handle cancel command.
    
    Args:
        payload: JSON dictionary with envelope pattern (header, params)
    
    Returns:
        True if command executed successfully, False on error
        Raises exception on unexpected errors
    """
    run_id = payload['header']['run_id']
    
    print(f"Cancelling command with run_id: {run_id}")
    print(f"Command: {payload['header']['command']}")
    print(f"Params: {payload['params']}")
    
    # Your cancel logic here
    # Call your machine control methods here
    # ...
    
    # Example: Call machine cancel method
    # success = await machine.cancel(run_id)
    
    # For now, simulate success
    success = True
    
    if success:
        print("Cancel command executed successfully")
        return True
    else:
        print("Cancel command failed")
        return False


async def main():
    # Initialize NATS client
    client = MachineNATSClient(
        servers=["nats://localhost:4222", "nats://localhost:4223", "nats://localhost:4224"],
        machine_id=MACHINE_ID
    )
    
    # Connect to NATS
    if not await client.connect():
        print("Failed to connect to NATS")
        return
    
    try:
        # Subscribe to commands
        await client.subscribe_execute(handle_execute_command)
        await client.subscribe_pause(handle_pause_command)
        await client.subscribe_cancel(handle_cancel_command)
        
        # Set initial status to idle
        await client.publish_status({'state': 'idle', 'run_id': None})
        
        print(f"NATS client connected and subscribed for machine: {MACHINE_ID}")
        print("Publishing sample telemetry...")
        
        # Publish event examples
        await client.publish_log('INFO', 'Machine started successfully')
        
        print("Sample telemetry published. Waiting for commands...")
        print("Press Ctrl+C to exit")
        
        # Keep running the telemetry loop
        while True:
            await asyncio.sleep(1)
            
            await client.publish_heartbeat()
            await client.publish_position({'x': 10.5, 'y': 20.3, 'z': 5.0})
            await client.publish_health({'cpu': 45.2, 'mem': 60.1, 'temp': 35.0})
            # Status is updated by command handlers, no need to publish here
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
