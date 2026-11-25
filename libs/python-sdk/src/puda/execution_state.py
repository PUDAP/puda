"""
Execution State Management
Tracks the queued command that is executing. Running commands are never
cancelled: estop and complete --abort stop them through the driver, and the
next command waits until the driver call returns.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ExecutionState:
    """
    Shared state for tracking command execution and cancellation.
    
    This class provides thread-safe access to:
    - Current executing task
    - Execution lock (to prevent concurrent commands)
    - Current run_id
    """
    def __init__(self):
        self._lock = asyncio.Lock()
        self._current_task: Optional[asyncio.Task] = None
        self._current_run_id: Optional[str] = None
    
    async def acquire_lock(self, run_id: str) -> bool:
        """
        Acquire the execution lock for a command.
        
        Args:
            run_id: Run ID of the command requesting execution
            
        Returns:
            True once the lock is held (commands run one at a time)
        """
        await self._lock.acquire()
        self._current_run_id = run_id
        return True
    
    def release_lock(self):
        """Release the execution lock."""
        self._current_run_id = None
        self._current_task = None
        self._lock.release()
    
    def set_current_task(self, task: asyncio.Task):
        """Set the currently executing task."""
        self._current_task = task
    
    def get_current_task(self) -> Optional[asyncio.Task]:
        """Get the currently executing task."""
        return self._current_task
    
    def get_current_run_id(self) -> Optional[str]:
        """Get the current run_id."""
        return self._current_run_id

    def get_runtime_status(self) -> str:
        """Return transient execution status without persisting it to KV."""
        return "busy" if self._lock.locked() else "idle"
