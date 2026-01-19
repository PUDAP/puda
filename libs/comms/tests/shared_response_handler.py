"""
Shared response handler for test scripts.
Manages response message handling using pull consumers for both queue and immediate responses.
Uses pull consumers to avoid workqueue stream uniqueness constraints.
Routes responses to waiting commands based on run_id and step_number.
"""
import asyncio
import json
import logging
from typing import Dict, Any, Tuple, Optional
from nats.js.client import JetStreamContext

logger = logging.getLogger(__name__)

NAMESPACE = "puda"


class SharedResponseHandler:
    """
    Manages response message handling using pull consumers.
    Uses pull consumers to avoid workqueue stream uniqueness constraints.
    Routes responses to waiting commands based on run_id and step_number.
    Handles both queue and immediate responses.
    """
    def __init__(self, js: JetStreamContext, machine_id: str):
        self.js = js
        self.machine_id = machine_id
        self._pending_responses: Dict[str, Dict[str, Any]] = {}
        self._queue_consumer = None
        self._immediate_consumer = None
        self._initialized = False
    
    async def _delete_all_consumers_on_subject(self, stream_name: str, consumer_patterns: list[str]):
        """
        Try to delete consumers that might conflict.
        This is a best-effort cleanup.
        
        Args:
            stream_name: Name of the stream
            consumer_patterns: List of consumer name patterns to try deleting
        """
        try:
            from nats.js.errors import NotFoundError
            
            for pattern in consumer_patterns:
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
        """Initialize the response handler using pull consumers for both queue and immediate responses."""
        if self._initialized:
            return
        
        queue_subject = f"{NAMESPACE}.{self.machine_id}.cmd.response.queue"
        immediate_subject = f"{NAMESPACE}.{self.machine_id}.cmd.response.immediate"
        
        try:
            # Try to delete existing consumers that might conflict
            queue_patterns = [
                f"response_queue_{self.machine_id}",
                f"response_immediate_{self.machine_id}",
                f"resp_q_{self.machine_id}",
                f"resp_i_{self.machine_id}",
            ]
            immediate_patterns = [
                f"response_immediate_{self.machine_id}",
                f"resp_i_{self.machine_id}",
                f"pull_resp_i_{self.machine_id}",
            ]
            
            await self._delete_all_consumers_on_subject("RESPONSE_QUEUE", queue_patterns)
            await self._delete_all_consumers_on_subject("RESPONSE_IMMEDIATE", immediate_patterns)
            
            # Create ephemeral consumers (they'll be cleaned up automatically)
            # Note: If this fails, there's still a consumer we couldn't delete
            self._queue_consumer = await self.js.subscribe(
                queue_subject,
                stream="RESPONSE_QUEUE",
                cb=lambda msg: asyncio.create_task(self._handle_message(msg))
            )
            
            self._immediate_consumer = await self.js.subscribe(
                immediate_subject,
                stream="RESPONSE_IMMEDIATE",
                cb=lambda msg: asyncio.create_task(self._handle_message(msg))
            )
            
            logger.info("Created consumers for queue and immediate response handling")
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Failed to initialize pull consumers: %s", error_msg)
            # Fallback: try to provide helpful error message
            if "filtered consumer not unique" in error_msg or "10100" in error_msg:
                error_details = (
                    "\n" + "=" * 80 +
                    "\nERROR: Cannot create consumer - another consumer already exists!\n"
                    f"Subjects: {queue_subject}, {immediate_subject}\n"
                    "Workqueue streams only allow ONE consumer per subject pattern.\n\n"
                    "SOLUTION: Delete existing consumers using NATS CLI:\n"
                    f"  nats consumer rm RESPONSE_QUEUE <consumer_name>\n"
                    f"  nats consumer rm RESPONSE_IMMEDIATE <consumer_name>\n\n"
                    "Or list consumers first:\n"
                    f"  nats consumer ls RESPONSE_QUEUE\n"
                    f"  nats consumer ls RESPONSE_IMMEDIATE\n" +
                    "=" * 80
                )
                logger.error("%s", error_details)
            raise
        
        self._initialized = True
    
    async def _handle_message(self, msg):
        """Handle incoming response messages."""
        try:
            response = json.loads(msg.data.decode())
            
            # Extract run_id and step_number from header
            header = response.get('header', {})
            resp_run_id = header.get('run_id')
            step_number = header.get('step_number')
            resp_command = header.get('command', 'unknown')
            
            # Extract result status from response.response.status
            result_data = response.get('result', {})
            status = result_data.get('status')
            
            # Look up pending response
            key = f"{resp_run_id}:{step_number}"
            if key in self._pending_responses:
                pending = self._pending_responses[key]
                
                # Print response clearly
                print("\n" + "=" * 80)
                print("RESPONSE RECEIVED:")
                print(f"  Command: {resp_command}")
                print(f"  Command ID: {step_number}")
                print(f"  Run ID: {resp_run_id}")
                print(f"  Status: {status.upper()}")
                
                if status == 'success':
                    print("  Result: SUCCESS")
                    pending['result']['result'] = True
                elif status == 'error':
                    error_msg = result_data.get('message', 'Unknown error')
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
    
    def register_pending(self, run_id: str, step_number: str) -> Tuple[asyncio.Event, Dict[str, Any]]:
        """
        Register a pending response and return event and result container.
        
        Args:
            run_id: Run ID for the command
            step_number: Command ID for the command
        
        Returns:
            Tuple of (event, result_container)
        """
        key = f"{run_id}:{step_number}"
        event = asyncio.Event()
        result_container = {'result': None}
        self._pending_responses[key] = {
            'event': event,
            'result': result_container
        }
        return event, result_container
    
    def remove_pending(self, run_id: str, step_number: str):
        """
        Remove a pending response registration.
        
        Args:
            run_id: Run ID for the command
            step_number: Command ID for the command
        """
        key = f"{run_id}:{step_number}"
        if key in self._pending_responses:
            del self._pending_responses[key]
    
    async def cleanup(self):
        """Clean up subscriptions."""
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


# Global instance to be shared across all test scripts
_global_handler: Optional[SharedResponseHandler] = None


def get_shared_handler(js: JetStreamContext, machine_id: str) -> SharedResponseHandler:
    """
    Get or create the global shared response handler instance.
    
    Args:
        js: JetStream context
        machine_id: Machine identifier
    
    Returns:
        SharedResponseHandler instance
    """
    global _global_handler
    
    if _global_handler is None:
        _global_handler = SharedResponseHandler(js, machine_id)
    
    return _global_handler


async def wait_for_response(
    handler: SharedResponseHandler,
    run_id: str,
    step_number: str,
    timeout: float = 60.0
) -> bool:
    """
    Wait for response using the shared response handler.
    
    Args:
        handler: SharedResponseHandler instance
        run_id: Run ID to wait for
        step_number: Command ID to wait for
        timeout: Maximum time to wait in seconds
    
    Returns:
        True if success, False if error
    """
    logger.info("Waiting for response (run_id: %s, step_number: %s, timeout: %s)...", 
                run_id, step_number, timeout)
    
    # Register pending response
    response_received, result_container = handler.register_pending(run_id, step_number)
    
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
    except TimeoutError:
        # Remove from pending if timeout
        handler.remove_pending(run_id, step_number)
        raise

