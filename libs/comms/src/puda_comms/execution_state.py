"""
Execution State Management
Provides thread-safe state tracking for command execution and cancellation.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ExecutionState:
    """
    Shared state for tracking command execution and cancellation.
    
    This class provides thread-safe access to:
    - Current executing task (for cancellation)
    - Execution lock (to prevent concurrent commands)
    - Current run_id (to match cancel with execute)
    """
    def __init__(self):
        self._lock = asyncio.Lock()
        self._current_task: Optional[asyncio.Task] = None
        self._current_run_id: Optional[str] = None
        self._cancelled = False
    
    async def acquire_execution(self, run_id: str) -> bool:
        """
        Acquire the execution lock for a command.
        
        Args:
            run_id: Run ID of the command requesting execution
            
        Returns:
            True if execution can proceed, False if cancelled or another command is running
        """
        await self._lock.acquire()
        if self._cancelled:
            self._lock.release()
            return False
        self._current_run_id = run_id
        return True
    
    def release_execution(self):
        """Release the execution lock."""
        self._current_run_id = None
        self._current_task = None
        self._cancelled = False
        self._lock.release()
    
    def set_current_task(self, task: asyncio.Task):
        """Set the currently executing task (for cancellation)."""
        self._current_task = task
    
    def get_current_task(self) -> Optional[asyncio.Task]:
        """Get the currently executing task."""
        return self._current_task
    
    def get_current_run_id(self) -> Optional[str]:
        """Get the current run_id."""
        return self._current_run_id
    
    async def cancel_current_execution(self, run_id: Optional[str] = None) -> bool:
        """
        Cancel the currently executing command.
        
        Args:
            run_id: Optional run_id to match. If provided, only cancels if it matches.
            
        Returns:
            True if cancellation was successful, False if no execution to cancel
        """
        if self._current_task is None:
            return False
        
        # If run_id provided, only cancel if it matches
        if run_id is not None and self._current_run_id != run_id:
            logger.warning("Cancel run_id %s doesn't match current run_id %s", 
                         run_id, self._current_run_id)
            return False
        
        if not self._current_task.done():
            logger.info("Cancelling execution (run_id: %s)", self._current_run_id)
            self._cancelled = True
            self._current_task.cancel()
            return True
        
        return False

