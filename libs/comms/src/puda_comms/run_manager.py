"""
Run State Management
Provides thread-safe run state tracking and validation for machine commands.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RunManager:
    """
    Manages run state for a machine.
    
    Tracks the active run_id and validates that commands match the active run.
    Provides thread-safe operations for run lifecycle management.
    """
    
    def __init__(self, machine_id: str):
        """
        Initialize RunManager for a machine.
        
        Args:
            machine_id: Machine identifier
        """
        self.machine_id = machine_id
        self._active_run_id: Optional[str] = None
        self._lock = asyncio.Lock()
    
    async def start_run(self, run_id: str) -> bool:
        """
        Set active run_id. Returns True if successful, False if run already active.
        
        Args:
            run_id: Run ID to set as active
            
        Returns:
            True if run was started successfully, False if another run is already active
        """
        async with self._lock:
            if self._active_run_id is not None:
                logger.warning(
                    "Cannot start run %s: run %s is already active on machine %s",
                    run_id, self._active_run_id, self.machine_id
                )
                return False
            
            self._active_run_id = run_id
            logger.info("Started run %s on machine %s", run_id, self.machine_id)
            return True
    
    async def complete_run(self, run_id: str) -> bool:
        """
        Clear run_id if it matches. Returns True if successful.
        
        Args:
            run_id: Run ID to complete
            
        Returns:
            True if run was completed successfully, False if run_id doesn't match active run
        """
        async with self._lock:
            if self._active_run_id != run_id:
                logger.warning(
                    "Cannot complete run %s: active run is %s on machine %s",
                    run_id, self._active_run_id, self.machine_id
                )
                return False
            
            self._active_run_id = None
            logger.info("Completed run %s on machine %s", run_id, self.machine_id)
            return True
    
    async def validate_run_id(self, run_id: str) -> bool:
        """
        Check if run_id matches active run. Returns True if valid.
        
        Args:
            run_id: Run ID to validate (required)
            
        Returns:
            True if run_id matches active run, False otherwise
        """
        async with self._lock:
            # If no active run, any run_id is invalid
            if self._active_run_id is None:
                logger.warning(
                    "Run ID validation failed: no active run, got %s on machine %s",
                    run_id, self.machine_id
                )
                return False
            
            # Run_id must match active run
            if self._active_run_id != run_id:
                logger.warning(
                    "Run ID validation failed: expected %s, got %s on machine %s",
                    self._active_run_id, run_id, self.machine_id
                )
                return False
            
            return True
    
    def get_active_run_id(self) -> Optional[str]:
        """
        Get current active run_id.
        
        Returns:
            Active run_id if one exists, None otherwise
        """
        return self._active_run_id

