import asyncio
import logging
import os
from dotenv import load_dotenv
from puda_drivers.machines import First
from puda_comms import MachineClient, ExecutionState
from puda_comms.models import CommandResponse, CommandResponseStatus, CommandResponseCode, NATSMessage

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Higher level logging for drivers
logging.getLogger("puda_drivers").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def main():
    # 1. Initialize Objects
    machine_id = os.getenv("MACHINE_ID", "first")
    # Get NATS servers from environment variable (comma-separated list)
    nats_servers_env = os.getenv(
        "NATS_SERVERS",
        "nats://192.168.50.201:4222,nats://192.168.50.201:4223,nats://192.168.50.201:4224"
    )
    nats_servers = [s.strip() for s in nats_servers_env.split(",")]
    
    client = MachineClient(
        servers=nats_servers,
        machine_id=machine_id
    )
    
    first_machine = First(
        qubot_port=os.getenv("QUBOT_PORT", "/dev/ttyACM0"),
        sartorius_port=os.getenv("SARTORIUS_PORT", "/dev/ttyUSB0"),
        camera_index=int(os.getenv("CAMERA_INDEX", "0")),
    )
    
    # Shared execution state for cancellation
    exec_state = ExecutionState()

    # 2. Setup Handlers
    async def handle_execute(message: NATSMessage) -> CommandResponse:
        if message.command is None:
            logger.error("Received message with no command")
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message="No command in message"
            )

        run_id = message.header.run_id
        command_name = message.command.name
        params = message.command.params

        # Try to acquire execution lock
        if not await exec_state.acquire_lock(run_id):
            logger.warning("Cannot execute %s (run_id: %s): another command is running or cancelled", 
                           command_name, run_id)
            await client.publish_state(
                {
                    'state': 'error',
                    'run_id': None,
                    'deck': first_machine.deck.to_dict()
                }
            )
            await client.publish_log('ERROR', f'Cannot execute {command_name}: another command is running')
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_LOCKED,
                message=f'Cannot execute {command_name}: another command is running or cancelled'
            )

        try:
            # Start execution lifecycle
            logger.info("Executing: %s (run_id: %s)", command_name, run_id)
            await client.publish_state({'state': 'busy', 'run_id': run_id, 'deck': first_machine.deck.to_dict()})
            
            # A. Safe Dispatching
            # Check if command exists on the object
            handler = getattr(first_machine, command_name, None)

            # Security: Ensure it's a method and not private (starts with _)
            if not callable(handler) or command_name.startswith('_'):
                logger.error("Unknown or restricted command: %s", command_name)
                await client.publish_state({'state': 'error', 'run_id': run_id, 'deck': first_machine.deck.to_dict()})
                return CommandResponse(
                    status=CommandResponseStatus.ERROR,
                    code=CommandResponseCode.UNKNOWN_COMMAND,
                    message=f"Unknown or restricted command: {command_name}"
                )

            # B. Execution
            # Wrap synchronous First machine methods in an executor so the async wrapper can be cancelled.
            # Note: The synchronous code in the executor will continue until it completes,
            # but we can cancel the async wrapper and prevent further status updates.
            async def execute_handler():
                # Run the synchronous handler in a thread pool
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: handler(**params))
            
            # Create and track the task
            task = asyncio.create_task(execute_handler())
            exec_state.set_current_task(task)
            
            try:
                await task
            except asyncio.CancelledError:
                logger.info("Handler execution cancelled (run_id: %s)", run_id)
                raise
                
            # Success path (only reached if no exception occurred)
            await client.publish_state({'state': 'idle', 'run_id': run_id, 'deck': first_machine.deck.to_dict()})
            await client.publish_log('INFO', f'Command {command_name} completed')
            return CommandResponse(status=CommandResponseStatus.SUCCESS)

        except asyncio.CancelledError:
            await client.publish_state({'state': 'idle', 'run_id': run_id, 'deck': first_machine.deck.to_dict()})
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.COMMAND_CANCELLED,
                message='Command was cancelled'
            )
        except Exception as e:
            # Recoverable errors: return error response with specific error message
            logger.error("Execute handler error (recoverable): %s", e, exc_info=True)
            await client.publish_state({'state': 'error', 'run_id': run_id, 'deck': first_machine.deck.to_dict()})
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=str(e)
            )
        finally:
            exec_state.release_lock()

    async def handle_immediate(message: NATSMessage) -> CommandResponse:
        """
        Handle immediate commands (pause, cancel, resume, etc.).
        Note: pause, resume, and cancel are handled by the client's built-in logic,
        but this handler can add custom logic on the machine side if needed.
        """
        if message.command is None:
            logger.error("Received immediate message with no command")
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message="No command in message"
            )
        
        command_name = message.command.name.lower()
        run_id = message.header.run_id

        # Built-in commands (pause, resume, cancel) are handled by the client
        # This handler is called for other immediate commands or for custom logic
        match command_name:
            case 'pause':
                # Custom pause logic if needed (beyond built-in handling)
                # Try to acquire execution lock for custom pause actions
                if not await exec_state.acquire_lock(run_id):
                    logger.warning("Cannot pause (run_id: %s): another command is running", run_id)
                    return CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.EXECUTION_LOCKED,
                        message='Cannot pause: another command is running'
                    )
                
                try:
                    # Add machine-specific pause logic here if needed
                    return CommandResponse(status=CommandResponseStatus.SUCCESS)
                except Exception as e:
                    return CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.PAUSE_ERROR,
                        message=str(e)
                    )
                finally:
                    exec_state.release_lock()
                    
            case 'resume':
                if not await exec_state.acquire_lock(run_id):
                    logger.warning("Cannot pause (run_id: %s): another command is running", run_id)
                    return CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.EXECUTION_LOCKED,
                        message='Cannot pause: another command is running'
                    )
                try:
                    # Custom resume logic if needed (beyond built-in handling)
                    return CommandResponse(status=CommandResponseStatus.SUCCESS)
                except Exception as e:
                    return CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.RESUME_ERROR,
                        message=str(e)
                    )
                finally:
                    exec_state.release_lock()
            
            case 'cancel':
                # Custom cancel logic if needed (beyond built-in handling)
                try:
                    # Try to cancel the current execution
                    cancelled = await exec_state.cancel_current_execution(run_id)
                    
                    if cancelled:
                        logger.info("Successfully cancelled execution (run_id: %s)", run_id)
                        await client.publish_log('INFO', f'Command cancelled (run_id: {run_id})')
                        return CommandResponse(status=CommandResponseStatus.SUCCESS)
                    else:
                        # No execution to cancel, or run_id doesn't match
                        current_task = exec_state.get_current_task()
                        current_run_id = exec_state.get_current_run_id()
                        
                        if current_task is None:
                            logger.warning("Cancel requested but no command is currently executing (run_id: %s)", run_id)
                            await client.publish_log('WARNING', f'Cancel requested but no command running (run_id: {run_id})')
                            return CommandResponse(
                                status=CommandResponseStatus.ERROR,
                                code=CommandResponseCode.NO_EXECUTION,
                                message='No command is currently executing'
                            )
                        else:
                            logger.warning("Cancel run_id %s doesn't match current run_id %s", 
                                         run_id, current_run_id)
                            await client.publish_log('ERROR', f'Cancel run_id mismatch (requested: {run_id}, current: {current_run_id})')
                            return CommandResponse(
                                status=CommandResponseStatus.ERROR,
                                code=CommandResponseCode.RUN_ID_MISMATCH,
                                message=f'Cancel run_id mismatch (requested: {run_id}, current: {current_run_id})'
                            )
                except Exception as e:
                    logger.error("Cancel handler error: %s", e, exc_info=True)
                    return CommandResponse(
                        status=CommandResponseStatus.ERROR,
                        code=CommandResponseCode.CANCEL_ERROR,
                        message=str(e)
                    )
                
            case _:
                # For other immediate commands, return success (handled by built-in logic or user)
                return CommandResponse(status=CommandResponseStatus.SUCCESS)

    # 3. Connect and Start Up (with retry logic)
    while True:
        if await client.connect():
            break
        else:
            logger.error("Failed to connect to NATS, retrying in 5 seconds...")
            await asyncio.sleep(5)

    # Start Hardware
    first_machine.startup()
    logger.info("Hardware initialized")

    async def setup_subscriptions():
        """Set up NATS subscriptions for queue and immediate commands."""
        await client.subscribe_queue(handle_execute)
        await client.subscribe_immediate(handle_immediate)

    async def ensure_connection() -> bool:
        """
        Ensure NATS connection is active, reconnect if needed.
        
        Returns:
            True if connected (or successfully reconnected), False if reconnection failed.
        """
        if client.nc is None or client.js is None:
            logger.warning("Connection lost, attempting to reconnect...")
            if await client.connect():
                # Re-subscribe after reconnection
                await setup_subscriptions()
                logger.info("Reconnected and re-subscribed")
                await client.publish_state({'state': 'idle', 'run_id': None, 'deck': first_machine.deck.to_dict()})
                return True
            else:
                logger.error("Reconnection failed, retrying in 5 seconds...")
                await asyncio.sleep(5)
                return False
        return True

    # Initial subscriptions
    await setup_subscriptions()

    logger.info("Machine %s Ready. Publishing telemetry...", machine_id)
    # Get the get_position method from the first_machine object
    get_position = getattr(first_machine, 'get_position')

    # 4. Main Loop - Never terminates
    while True:
        try:
            # Ensure we're still connected, reconnect if needed
            if not await ensure_connection():
                continue

            # Telemetry Loop (Keeps the script running)
            try:
                await client.publish_heartbeat()
                position = await get_position()
                await client.publish_position(position)
                await client.publish_health({'cpu': 45.2, 'mem': 60.1, 'temp': 35.0})
                await asyncio.sleep(1)
            except Exception as e:
                # Log telemetry errors but continue running
                logger.error("Error publishing telemetry: %s", e, exc_info=True)
                await asyncio.sleep(1)  # Wait before retrying telemetry

        except asyncio.CancelledError:
            # Should not happen in main loop, but if it does, continue running
            logger.warning("Received CancelledError in main loop, continuing...")
            await asyncio.sleep(1)
        except Exception as e:
            # Catch all other exceptions and continue running
            logger.error("Unexpected error in main loop: %s", e, exc_info=True)
            await asyncio.sleep(5)  # Wait before retrying

if __name__ == "__main__":
    # Run forever - never exit
    import time
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            # Even on KeyboardInterrupt, log and continue
            logger.warning("Received KeyboardInterrupt, but continuing to run...")
            time.sleep(1)
        except Exception as e:
            # Catch any other exceptions and restart
            logger.error("Fatal error in main: %s", e, exc_info=True)
            time.sleep(5)