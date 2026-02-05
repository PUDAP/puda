"""
Main entry point for the Biologic machine edge service.

This module provides the main event loop for the Biologic machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
import os
import sys
from typing import Any
from dotenv import load_dotenv
from biologic_machine import BiologicMachine
from puda_comms import MachineClient, ExecutionState
from puda_comms.models import CommandResponse, CommandResponseStatus, CommandResponseCode, NATSMessage
from puda_drivers.machines import Biologic

# Load environment variables from .env file
load_dotenv()

# Configure logging with immediate flushing
class FlushingStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after each log message."""
    def emit(self, record):
        super().emit(record)
        self.flush()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True,  # Force reconfiguration if already configured
    handlers=[FlushingStreamHandler()]  # Use flushing handler
)
# Higher level logging for drivers
logger = logging.getLogger(__name__)

def _convert_handler_result_to_dict(result: Any) -> dict | None:
    """
    Convert handler result to a dictionary format suitable for JSON serialization.
    
    Args:
        result: Handler return value (can be dict, Pydantic model, object with to_dict(), etc.)
        
    Returns:
        Dictionary representation of the result, or None if result is None
    """
    if result is None:
        return None
    
    if isinstance(result, dict):
        return result
    
    if hasattr(result, 'model_dump'):
        # Pydantic model
        return result.model_dump()
    
    if hasattr(result, 'to_dict') and callable(result.to_dict):
        # Object with to_dict() method (e.g., Position)
        return result.to_dict()
    
    if hasattr(result, '__dict__'):
        # Object with __dict__
        return result.__dict__
    
    # Primitive type or other - wrap in a dict
    return {'result': result}


async def main():
    # Log immediately to verify function is called
    logger.info("=== Starting Biologic edge service ===")
    
    # 1. Initialize Objects
    machine_id = os.getenv("MACHINE_ID")
    if not machine_id:
        raise ValueError("MACHINE_ID environment variable is required")

    biologic_ip = os.getenv("BIOLOGIC_IP")
    if not biologic_ip:
        raise ValueError("BIOLOGIC_IP environment variable is required")

    nats_servers_env = os.getenv("NATS_SERVERS")
    if not nats_servers_env:
        raise ValueError("NATS_SERVERS environment variable is required")
    nats_servers = [s.strip() for s in nats_servers_env.split(",")]
    
    # 2. Initialize Biologic machine
    logger.info("Initializing Biologic machine with IP: %s", biologic_ip)
    biologic_machine = BiologicMachine(device_ip=biologic_ip)
    
    # 3. Initialize NATS client
    logger.info("Initializing NATS client with servers: %s", nats_servers)
    client = MachineClient(
        servers=nats_servers,
        machine_id=machine_id
    )
    
    # 4. Connect to NATS (with retry logic)
    while True:
        if await client.connect():
            break
        else:
            logger.error("Failed to connect to NATS, retrying in 5 seconds...")
            await asyncio.sleep(5)
    
    # Shared execution state for cancellation
    exec_state = ExecutionState()

    # 2. Setup Handlers
    async def _publish_state(state: str, run_id: str | None = None):
        """Helper to publish state."""
        await client.publish_state({
            'state': state,
            'run_id': run_id
        })
    
    def _validate_handler(command_name: str):
        """
        Validate that a command handler exists and is callable.
        
        Returns:
            tuple: (handler, error_response) where handler is callable or None,
                   and error_response is None if valid, otherwise a CommandResponse
        """
        handler = getattr(biologic_machine, command_name, None)
        
        if not callable(handler) or command_name.startswith('_'):
            logger.error("Unknown or restricted command: %s", command_name)
            return None, CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.UNKNOWN_COMMAND,
                message=f"Unknown or restricted command: {command_name}"
            )
        
        return handler, None
    
    async def _execute_handler(handler, params: dict):
        """
        Execute a synchronous handler in a thread pool executor.
        This allows the async wrapper to be cancelled.
        """
        # Ensure params is a dict (not None or other type)
        if not isinstance(params, dict):
            params = {}
        
        # Extract 'channels' from params if present, to pass as kwargs
        kwargs = {}
        if 'channels' in params:
            kwargs['channels'] = params.pop('channels')
        
        loop = asyncio.get_event_loop()
        print("executing handler with params:", params, "and kwargs:", kwargs)
        return await loop.run_in_executor(None, lambda: handler(params=params, **kwargs))
    
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
        params = message.command.params or {}

        # Try to acquire execution lock
        if not await exec_state.acquire_lock(run_id):
            logger.warning("Cannot execute %s (run_id: %s): another command is running or cancelled", 
                           command_name, run_id)
            await _publish_state('error', run_id=None)
            await client.publish_log('ERROR', f'Cannot execute {command_name}: another command is running')
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_LOCKED,
                message=f'Cannot execute {command_name}: another command is running or cancelled'
            )

        try:
            logger.info("Executing: %s (run_id: %s)", command_name, run_id)
            await _publish_state('busy', run_id)
            
            # Validate handler
            handler, error_response = _validate_handler(command_name)
            if error_response is not None:
                await _publish_state('error', run_id)
                return error_response

            # Execute handler in thread pool
            task = asyncio.create_task(_execute_handler(handler, params))
            exec_state.set_current_task(task)
            
            try:
                handler_result = await task
            except asyncio.CancelledError:
                # if command cancelled while executing, return error response
                logger.info("Handler execution cancelled (run_id: %s)", run_id)
                return CommandResponse(
                    status=CommandResponseStatus.ERROR,
                    code=CommandResponseCode.COMMAND_CANCELLED,
                    message='Command was cancelled'
                )
                
            # Success path
            await _publish_state('idle', run_id)
            await client.publish_log('INFO', f'Command {command_name} completed')
            
            return CommandResponse(
                status=CommandResponseStatus.SUCCESS,
                data=_convert_handler_result_to_dict(handler_result)
            )

        except Exception as e:
            logger.error("Execute handler error (recoverable): %s", e, exc_info=True)
            await _publish_state('error', run_id)
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
        Executes the corresponding handler method from biologic_machine.
        """
        if message.command is None:
            logger.error("Received immediate message with no command")
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message="No command in message"
            )
        
        command_name = message.command.name
        params = message.command.params or {}
        run_id = message.header.run_id

        try:
            logger.info("Executing immediate command: %s (run_id: %s)", command_name, run_id)
            
            # Validate handler
            handler, error_response = _validate_handler(command_name)
            if error_response is not None:
                return error_response

            # Execute handler in thread pool (for consistency with execute handler)
            handler_result = await _execute_handler(handler, params)
            
            logger.info("Immediate command %s completed (run_id: %s)", command_name, run_id)
            
            return CommandResponse(
                status=CommandResponseStatus.SUCCESS,
                data=_convert_handler_result_to_dict(handler_result)
            )

        except Exception as e:
            logger.error("Immediate command handler error: %s", e, exc_info=True)
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=str(e)
            )

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
                await client.publish_state({'state': 'idle', 'run_id': None})
                return True
            else:
                logger.error("Reconnection failed, retrying in 5 seconds...")
                await asyncio.sleep(5)
                return False
        return True

    # Initial subscriptions
    await setup_subscriptions()

    logger.info("==================== Machine %s Ready. Publishing telemetry... ====================", machine_id)

    # 4. Main Loop - Never terminates
    while True:
        try:
            # Ensure we're still connected, reconnect if needed
            if not await ensure_connection():
                continue

            # Telemetry Loop (Keeps the script running)
            try:
                await client.publish_heartbeat()
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