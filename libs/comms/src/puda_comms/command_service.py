"""
Service for sending commands to machines via NATS. Should take in AI generated commands as CommandRequest models.

This service handles:
- Connecting to NATS servers
- Parsing and sending commands to the correct topics (queue/immediate)
- Waiting for and handling responses
- Managing command lifecycle (run_id, step_number, etc.)
"""
import asyncio
import json
import logging
import signal
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import nats
from nats.js.client import JetStreamContext
from nats.aio.msg import Msg
from puda_comms.models import (
    CommandRequest,
    CommandResponseStatus,
    NATSMessage,
    MessageHeader,
    MessageType,
)

logger = logging.getLogger(__name__)

# Constants
NAMESPACE = "puda"
STREAM_COMMAND_QUEUE = "COMMAND_QUEUE"
STREAM_COMMAND_IMMEDIATE = "COMMAND_IMMEDIATE"
STREAM_RESPONSE_QUEUE = "RESPONSE_QUEUE"
STREAM_RESPONSE_IMMEDIATE = "RESPONSE_IMMEDIATE"


class ResponseHandler:
    """
    Handles response messages from a specific machine.
    Routes responses to waiting commands based on run_id and step_number.
    """
    
    def __init__(self, js: JetStreamContext, machine_id: str):
        self.js = js
        self.machine_id = machine_id
        self._pending_responses: Dict[str, Dict[str, Any]] = {}  # {'event': asyncio.Event, 'response': Optional[NATSMessage]}
        self._queue_consumer = None
        self._immediate_consumer = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the response handler by subscribing to response streams."""
        if self._initialized:
            return
        
        # push consumers with ephemeral subscriptions
        queue_subject = f"{NAMESPACE}.{self.machine_id}.cmd.response.queue"
        immediate_subject = f"{NAMESPACE}.{self.machine_id}.cmd.response.immediate" 
        
        try:
            # Create ephemeral consumers for response streams
            self._queue_consumer = await self.js.subscribe(
                queue_subject,
                stream=STREAM_RESPONSE_QUEUE,
                cb=lambda msg: asyncio.create_task(self._handle_message(msg))
            )
            
            self._immediate_consumer = await self.js.subscribe(
                immediate_subject,
                stream=STREAM_RESPONSE_IMMEDIATE,
                cb=lambda msg: asyncio.create_task(self._handle_message(msg))
            )
            
            logger.info("Response handler initialized for machine: %s", self.machine_id)
            self._initialized = True
            
        except Exception as e:
            logger.error("Failed to initialize response handler: %s", e)
            raise
    
    async def _handle_message(self, msg: Msg):
        """Handle incoming response messages."""
        try:
            message = NATSMessage.model_validate_json(msg.data)
            command = message.command.name
            run_id = message.header.run_id
            step_number = message.command.step_number
            
            # Check if we have required fields for matching
            if run_id is None or step_number is None:
                logger.error(
                    "Response missing required fields: command=%s, step_number=%s, run_id=%s - putting back in queue",
                    command, step_number, run_id
                )
                await msg.nak()
                return
            
            # Look up pending response
            key = f"{run_id}:{step_number}"
            if key in self._pending_responses:
                
                logger.info(
                    "Response received: command=%s, step_number=%s, run_id=%s, status=%s",
                    command, step_number, run_id, message.response.status
                )
                if message.response.status == CommandResponseStatus.ERROR:
                    logger.warning("Command failed: %s", message.response.message)
                
                # Get the pending response
                pending = self._pending_responses[key]
                # Store the NATSMessage directly
                pending['response'] = message
                # Signal that response was received
                # Don't delete here - let get_response() delete it after retrieval
                pending['event'].set()
                
                # Acknowledge the message since we matched it
                await msg.ack()
            else:
                # No matching pending command - acknowledge to remove from queue
                # This response is likely from a previous run or different session
                logger.debug(
                    "Unmatched response (acknowledging): command=%s, step_number=%s, run_id=%s",
                    command, step_number, run_id
                )
                await msg.ack()
            
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.error("Error processing response message: %s", e)
            try:
                await msg.ack()
            except Exception:
                pass
        except Exception as e:
            logger.error("Unexpected error processing response message: %s", e)
            try:
                await msg.ack()
            except Exception:
                pass
    
    def register_pending(self, run_id: str, step_number: int) -> asyncio.Event:
        """
        Register a pending response and return event.
        
        Args:
            run_id: Run ID for the command
            step_number: Step number for the command
        
        Returns:
            Event that will be set when the response is received
        """
        key = f"{run_id}:{str(step_number)}"
        event = asyncio.Event()
        # Store None initially, will be updated with the response
        self._pending_responses[key] = {
            'event': event,
            'response': None
        }
        return event
    
    def get_response(self, run_id: str, step_number: int) -> Optional[NATSMessage]:
        """
        Get the response for a pending command.
        
        Args:
            run_id: Run ID for the command
            step_number: Step number for the command
        
        Returns:
            The NATSMessage if available, None otherwise
        """
        key = f"{run_id}:{str(step_number)}"
        if key in self._pending_responses:
            response = self._pending_responses[key].get('response')
            # Delete after retrieval to clean up
            del self._pending_responses[key]
            return response
        return None
    
    def remove_pending(self, run_id: str, step_number: int):
        """Remove a pending response registration."""
        key = f"{run_id}:{str(step_number)}"
        if key in self._pending_responses:
            del self._pending_responses[key]
    
    def cancel_all_pending(self):
        """Cancel all pending responses by setting their events. This wakes up any waiting tasks immediately."""
        for pending in self._pending_responses.values():
            pending['event'].set()
    
    async def cleanup(self):
        """Clean up subscriptions."""
        # Cancel all pending responses first to wake up waiting tasks
        self.cancel_all_pending()
        
        if self._queue_consumer:
            try:
                await self._queue_consumer.unsubscribe()
            except Exception:
                pass
        
        if self._immediate_consumer:
            try:
                await self._immediate_consumer.unsubscribe()
            except Exception:
                pass


class CommandService:
    """
    Service for sending commands to machines via NATS.
    
    Handles connection management, command parsing, and response handling.
    Can send commands to multiple machines.
    
    Automatically registers signal handlers (SIGTERM, SIGINT) for graceful shutdown.
    """
    
    # ==================== Initialization ====================
    
    def __init__(
        self,
        servers: list[str]
    ):
        """
        Initialize NATS service.
        
        Args:
            servers: List of NATS server URLs. Must be a non-empty list.
        
        Raises:
            ValueError: If servers is None or empty.
        """
        if servers is None or len(servers) == 0:
            raise ValueError("Please provide a non-empty list of NATS server URLs")
        
        self.servers = servers
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self._response_handlers: Dict[str, ResponseHandler] = {} # stores response handlers for each machine
        self._connected = False
        
        # Always register signal handlers for graceful shutdown
        self._register_signal_handlers()
    
    # ==================== Context Manager ====================
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False  # Don't suppress exceptions
    
    # ==================== Connection Management ====================
    
    async def connect(self) -> bool:
        """
        Connect to NATS servers.
        
        Limits connection attempts to 3. After 3 failed attempts, gives up and logs error.
        
        Returns:
            True if connected successfully, False otherwise
        """
        if self._connected:
            return True
        
        max_attempts = 3
        connect_timeout = 3  # 3 seconds timeout per connection attempt
        
        for attempt in range(max_attempts):
            try:
                logger.info("Connection attempt %d/%d to NATS servers: %s", attempt + 1, max_attempts, self.servers)
                self.nc = await asyncio.wait_for(
                    nats.connect(
                        servers=self.servers,
                        connect_timeout=connect_timeout,
                        reconnect_time_wait=2,
                        max_reconnect_attempts=0  # No reconnection during initial connection
                    ),
                    timeout=connect_timeout + 1  # Slightly longer timeout for the wait_for
                )
                self.js = self.nc.jetstream()
                
                self._connected = True
                logger.info("Connected to NATS servers")
                return True
                
            except asyncio.TimeoutError:
                logger.warning("Connection attempt %d/%d timed out after %d seconds", attempt + 1, max_attempts, connect_timeout)
                if attempt < max_attempts - 1:
                    logger.info("Retrying connection...")
                else:
                    logger.error("Failed to connect after %d attempts. Giving up.", max_attempts)
            except Exception as e:
                logger.warning("Connection attempt %d/%d failed: %s", attempt + 1, max_attempts, e)
                if attempt < max_attempts - 1:
                    logger.info("Retrying connection...")
                else:
                    logger.error("Failed to connect after %d attempts. Giving up.", max_attempts)
        
        self._connected = False
        return False
    
    async def _get_response_handler(self, machine_id: str) -> ResponseHandler:
        """
        Get or create a response handler for the specified machine.
        
        Args:
            machine_id: Machine identifier
        
        Returns:
            ResponseHandler instance for the machine
        """
        if machine_id not in self._response_handlers:
            handler = ResponseHandler(self.js, machine_id)
            await handler.initialize()
            self._response_handlers[machine_id] = handler
        
        return self._response_handlers[machine_id]
    
    async def disconnect(self):
        """Disconnect from NATS servers and cleanup."""
        if not self._connected:
            return
        
        # Cleanup all response handlers
        for handler in self._response_handlers.values():
            await handler.cleanup()
        self._response_handlers.clear()
        
        if self.nc:
            await self.nc.close()
            self.nc = None
            self.js = None
        
        self._connected = False
        logger.info("Disconnected from NATS")
    
    # ==================== Public Command Methods ====================
    
    async def send_queue_command(
        self,
        *,
        request: CommandRequest,
        machine_id: str,
        run_id: str,
        user_id: str,
        username: str,
        timeout: int = 120
    ) -> Optional[NATSMessage]:
        """
        Send a queue command to the machine and wait for response.
        
        Args:
            request: CommandRequest model containing command details
            machine_id: Machine ID to send the command to
            run_id: Run ID for the command
            user_id: User ID who initiated the command
            username: Username who initiated the command
            timeout: Maximum time to wait for response in seconds
        
        Returns:
            CommandResponse if successful, None if failed or timeout
        """
        if not self._connected or not self.js:
            raise RuntimeError("Not connected to NATS. Call connect() first.")
        
        # Determine subject
        subject = f"{NAMESPACE}.{machine_id}.cmd.queue"
        
        logger.info(
            "Sending queue command: subject=%s, command=%s, run_id=%s, step_number=%s",
            subject, request.name, run_id, request.step_number
        )
        
        # Get or create response handler for this machine
        response_handler = await self._get_response_handler(machine_id)
        # Register pending response
        response_event = response_handler.register_pending(run_id, request.step_number)
        
        # Build payload
        payload = self._build_command_payload(request, machine_id, run_id, user_id, username)

        try:
            # Publish to JetStream
            pub_ack = await self.js.publish(
                subject,
                payload.model_dump_json().encode()
            )
            
            logger.info("Command published (step_number: %s), waiting for response...", request.step_number)
            
            # Wait for response with timeout
            try:
                await asyncio.wait_for(response_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for response after %s seconds", timeout)
                response_handler.remove_pending(run_id, request.step_number)
                return None
            
            # Give a small delay to ensure any pending messages are processed
            await asyncio.sleep(0.1)
            
            # Get the response
            return response_handler.get_response(run_id, request.step_number)

        except Exception as e:
            logger.error("Error sending queue command: %s", e)
            response_handler.remove_pending(run_id, request.step_number)
            return None
    
    async def start_run(
        self,
        machine_id: str,
        run_id: str,
        user_id: str,
        username: str,
        timeout: int = 120
    ) -> Optional[NATSMessage]:
        """
        Send START immediate command to begin a run.
        
        Args:
            machine_id: Machine ID to send the command to
            run_id: Run ID for the command
            user_id: User ID who initiated the command
            username: Username who initiated the command
            timeout: Maximum time to wait for response in seconds
        
        Returns:
            NATSMessage if successful, None if failed or timeout
        """
        request = CommandRequest(
            name="start",
            params={},
            step_number=0
        )
        return await self.send_immediate_command(
            request=request,
            machine_id=machine_id,
            run_id=run_id,
            user_id=user_id,
            username=username,
            timeout=timeout
        )
    
    async def complete_run(
        self,
        machine_id: str,
        run_id: str,
        user_id: str,
        username: str,
        timeout: int = 120
    ) -> Optional[NATSMessage]:
        """
        Send COMPLETE immediate command to end a run.
        
        Args:
            machine_id: Machine ID to send the command to
            run_id: Run ID for the command
            user_id: User ID who initiated the command
            username: Username who initiated the command
            timeout: Maximum time to wait for response in seconds
        
        Returns:
            NATSMessage if successful, None if failed or timeout
        """
        request = CommandRequest(
            name="complete",
            params={},
            step_number=0
        )
        return await self.send_immediate_command(
            request=request,
            machine_id=machine_id,
            run_id=run_id,
            user_id=user_id,
            username=username,
            timeout=timeout
        )
    
    async def send_queue_commands(
        self,
        *,
        requests: list[CommandRequest],
        machine_id: str,
        run_id: str,
        user_id: str,
        username: str,
        timeout: int = 120
    ) -> Optional[NATSMessage]:
        """
        Send multiple queue commands sequentially and wait for responses.
        
        Automatically sends START command before the sequence and COMPLETE command after
        successful completion. Sends commands one by one, waiting for each response before
        sending the next. If any command fails or times out, stops immediately and returns
        the error response. If all commands succeed, returns the last command's response.
        
        Args:
            requests: List of CommandRequest models to send sequentially
            machine_id: Machine ID to send the commands to
            run_id: Run ID for all commands
            user_id: User ID who initiated the commands
            username: Username who initiated the commands
            timeout: Maximum time to wait for each response in seconds
        
        Returns:
            NATSMessage of the failed command if any command fails, or the last
            command's response if all succeed. Returns None if a command times out.
        """
        if not self._connected or not self.js:
            raise RuntimeError("Not connected to NATS. Call connect() first.")
        
        if not requests:
            logger.warning("No commands to send")
            return None
        
        logger.info(
            "Sending %d queue commands sequentially: machine_id=%s, run_id=%s",
            len(requests),
            machine_id,
            run_id
        )
        
        # Always send START command before sequence
        logger.info("Sending START command before sequence")
        start_response = await self.start_run(
            machine_id=machine_id,
            run_id=run_id,
            user_id=user_id,
            username=username,
            timeout=timeout
        )
        if start_response is None:
            logger.error("START command timed out")
            return None
        if start_response.response and start_response.response.status == CommandResponseStatus.ERROR:
            logger.error("START command failed: %s", start_response.response.message)
            return start_response
        
        last_response: Optional[NATSMessage] = None
        
        try:
            for idx, request in enumerate(requests, start=1):
                logger.info(
                    "Sending command %d/%d: %s (step %s)",
                    idx,
                    len(requests),
                    request.name,
                    request.step_number
                )
                
                response = await self.send_queue_command(
                    request=request,
                    machine_id=machine_id,
                    run_id=run_id,
                    user_id=user_id,
                    username=username,
                    timeout=timeout
                )
                
                # Check if command failed (None means timeout or exception)
                if response is None:
                    logger.error(
                        "Command %d/%d failed or timed out: %s (step %s)",
                        idx,
                        len(requests),
                        request.name,
                        request.step_number
                    )
                    return None
                
                # Check if command returned an error status
                if response.response is not None:
                    if response.response.status == CommandResponseStatus.ERROR:
                        logger.error(
                            "Command %d/%d failed with error: %s (step %s) - code: %s, message: %s",
                            idx,
                            len(requests),
                            request.name,
                            request.step_number,
                            response.response.code,
                            response.response.message
                        )
                        return response
                    
                    # Command succeeded, store as last response
                    last_response = response
                    logger.info(
                        "Command %d/%d succeeded: %s (step %s)",
                        idx,
                        len(requests),
                        request.name,
                        request.step_number
                    )
                else:
                    # Response exists but has no response data (shouldn't happen, but handle it)
                    logger.warning(
                        "Command %d/%d returned response with no response data: %s (step %s)",
                        idx,
                        len(requests),
                        request.name,
                        request.step_number
                    )
                    return response
            
            logger.info(
                "All %d commands completed successfully",
                len(requests)
            )
            
            # Always send COMPLETE command after successful sequence
            logger.info("Sending COMPLETE command after successful sequence")
            complete_response = await self.complete_run(
                machine_id=machine_id,
                run_id=run_id,
                user_id=user_id,
                username=username,
                timeout=timeout
            )
            if complete_response is None:
                logger.error("COMPLETE command timed out")
                return None
            if complete_response.response and complete_response.response.status == CommandResponseStatus.ERROR:
                logger.error("COMPLETE command failed: %s", complete_response.response.message)
                return complete_response
            # Return the last command response, not the COMPLETE response
            return last_response
        except Exception as e:
            # If any error occurs during command execution, try to complete the run
            # to clean up state (but don't fail if this also fails)
            logger.warning("Error during command sequence, attempting to complete run: %s", e)
            try:
                await self.complete_run(
                    machine_id=machine_id,
                    run_id=run_id,
                    user_id=user_id,
                    username=username,
                    timeout=timeout
                )
            except Exception as cleanup_error:
                logger.error("Failed to complete run during error cleanup: %s", cleanup_error)
            raise
    
    async def send_immediate_command(
        self,
        *,
        request: CommandRequest,
        machine_id: str,
        run_id: str,
        user_id: str,
        username: str,
        timeout: int = 120
    ) -> Optional[NATSMessage]:
        """
        Send an immediate command (pause, resume, cancel) to the machine.
        
        Args:
            request: CommandRequest model containing command details
            machine_id: Machine ID to send the command to
            run_id: Run ID for the command
            user_id: User ID who initiated the command
            username: Username who initiated the command
            timeout: Maximum time to wait for response in seconds
        
        Returns:
            NATSMessage if successful, None if failed or timeout
        """
        if not self._connected or not self.js:
            raise RuntimeError("Not connected to NATS. Call connect() first.")
        
        
        # Determine subject
        subject = f"{NAMESPACE}.{machine_id}.cmd.immediate"
        
        logger.info(
            "Sending immediate command: machine_id=%s, command=%s, run_id=%s, step_number=%s",
            machine_id, request.name, run_id, request.step_number
        )
        
        # Get or create response handler for this machine
        response_handler = await self._get_response_handler(machine_id)
        
        # Register pending response
        response_received = response_handler.register_pending(run_id, request.step_number)
        
        # Build payload
        payload = self._build_command_payload(request, machine_id, run_id, user_id, username)

        try:
            # Publish to JetStream
            pub_ack = await self.js.publish(
                subject,
                payload.model_dump_json().encode()
            )
            
            logger.info("Command published, waiting for response...")
            
            # Wait for response with timeout
            try:
                await asyncio.wait_for(response_received.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for response after %s seconds", timeout)
                response_handler.remove_pending(run_id, request.step_number)
                return None
            
            # Give a small delay to ensure any pending messages are processed
            await asyncio.sleep(0.1)
            
            # Get the response
            return response_handler.get_response(run_id, request.step_number)
            
        except Exception as e:
            logger.error("Error sending immediate command: %s", e)
            response_handler.remove_pending(run_id, request.step_number)
            return None
    
    # ==================== Private Helper Methods ====================
    
    def _register_signal_handlers(self):
        """Register signal handlers for graceful shutdown."""
        def signal_handler(signum, _frame):
            """Handle shutdown signals by scheduling disconnect."""
            logger.info("Received signal %s, initiating graceful shutdown...", signum)
            try:
                # Try to get the running event loop
                loop = asyncio.get_running_loop()
                # Schedule disconnect as a task in the running loop
                def schedule_disconnect():
                    asyncio.create_task(self.disconnect())
                loop.call_soon_threadsafe(schedule_disconnect)
            except RuntimeError:
                # No running loop, create a new one and run disconnect
                asyncio.run(self.disconnect())
            except Exception as e:
                logger.error("Error during signal handler disconnect: %s", e)
        
        # Register handlers for SIGTERM and SIGINT
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        logger.debug("Signal handlers registered for SIGTERM and SIGINT")
    
    async def _get_response_handler(self, machine_id: str) -> ResponseHandler:
        """
        Get or create a response handler for the specified machine.
        
        Args:
            machine_id: Machine identifier
        
        Returns:
            ResponseHandler instance for the machine
        """
        if machine_id not in self._response_handlers:
            handler = ResponseHandler(self.js, machine_id)
            await handler.initialize()
            self._response_handlers[machine_id] = handler
        
        return self._response_handlers[machine_id]
    
    def _build_command_payload(
        self,
        command_request: CommandRequest,
        machine_id: str,
        run_id: str,
        user_id: str,
        username: str
    ) -> NATSMessage:
        """
        Build a command payload in the expected format.
        
        Args:
            command_request: CommandRequest model containing command details
            machine_id: Machine ID for the command
            run_id: Run ID for the command (empty string will be converted to None)
            user_id: User ID who initiated the command
            username: Username who initiated the command
        
        Returns:
            NATSMessage object ready for NATS transmission
        """
        # Convert empty string to None for run_id
        run_id_value = run_id if run_id else None
        
        header = MessageHeader(
            message_type=MessageType.COMMAND,
            version="1.0",
            timestamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            user_id=user_id,
            username=username,
            machine_id=machine_id,
            run_id=run_id_value
        )
        
        return NATSMessage(
            header=header,
            command=command_request
        )
