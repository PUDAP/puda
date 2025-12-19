"""
Base Robot Interface
Abstract base class for machine implementations that can be reused for different machine types
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MachineConfig:
    """
    Configuration for a machine.
    """
    machine_id: str  # e.g., "ot2_01" etc.
    capabilities: list[str] = []
class BaseMachine(ABC):
    """
    Abstract base class for machine implementations.
    Subclasses must implement machine-specific functions
    """
    
    def __init__(self, config: MachineConfig):
        self.config = config

        self._connected: bool = False
        self._machine_id: str = config.machine_id
        self._capabilities: list[str] = config.capabilities
        
    @property
    def connected(self) -> bool:
        """
        Get connection status.
        """
        return self._connected
    
    @connected.setter
    def connected(self, value: bool):
        """
        Set connection status.
        """
        self._connected = value
    
    @property
    def machine_id(self) -> str:
        """
        Get machine ID.
        """
        return self._machine_id
    
    @property
    def capabilities(self) -> list[str]:
        """
        Get list of machine capabilities.
        """
        return self._capabilities
    
    @abstractmethod
    async def check_connection(self) -> bool:
        """
        Check if machine is accessible.
        Returns True if machine is online and accessible.
        """
    
    @abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        """
        Get current machine status and health information.
        Returns dict with machine status, health, capabilities, etc.
        """
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get device information for registration/status updates.
        Can be overridden by subclasses for additional info.
        """
        return {
            'machine_id': self._machine_id,
            'capabilities': self._capabilities,
        }
