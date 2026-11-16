"""
puda-data Device Adapters

Abstract base class and registry for device-specific data extraction.
Each adapter knows how to extract and interpret data from a specific device.

Usage:
    # Get adapter for a device
    adapter = AdapterRegistry.get("first")
    df = adapter.extract_data(payload, "CV")

    # Register a new adapter
    AdapterRegistry.register(MyAdapter())
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Type
import pandas as pd

from registry import SchemaRegistry


class DeviceAdapter(ABC):
    """
    Base class for device-specific data extraction.

    Each adapter knows:
    - How to navigate the device's payload structure
    - What schema to use for each command type
    - Device-specific quirks or transformations
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this device (e.g., 'first', 'biologic')."""
        pass

    @abstractmethod
    def extract_data(self, payload: Dict[str, Any], command: str) -> pd.DataFrame:
        """
        Extract measurement data from device payload.

        Args:
            payload: Raw device response payload
            command: Command type (CV, OCV, PEIS, etc.)

        Returns:
            DataFrame with proper column names from schema
        """
        pass

    def get_schema(self, command: str) -> Any:
        """Get schema for this device's command type."""
        return SchemaRegistry.get_or_default(self.name, command)


class AdapterRegistry:
    """
    Registry for device adapters.

    Usage:
        AdapterRegistry.register(FirstMachineAdapter())
        adapter = AdapterRegistry.get("first")
    """

    _adapters: Dict[str, DeviceAdapter] = {}

    @classmethod
    def register(cls, adapter: DeviceAdapter) -> None:
        """Register a device adapter."""
        cls._adapters[adapter.name.lower()] = adapter

    @classmethod
    def get(cls, device: str) -> Optional[DeviceAdapter]:
        """Get adapter for device, or None if not found."""
        return cls._adapters.get(device.lower())

    @classmethod
    def get_or_default(cls, device: str) -> DeviceAdapter:
        """Get adapter or return a generic fallback."""
        adapter = cls.get(device)
        if adapter:
            return adapter
        return GenericAdapter(device)

    @classmethod
    def list_devices(cls) -> List[str]:
        """List all registered device names."""
        return list(cls._adapters.keys())


class GenericAdapter(DeviceAdapter):
    """
    Fallback adapter for unknown devices.

    Attempts to extract data using generic heuristics:
    - Looks for 'data' or 'response' keys
    - Uses schema registry or column count to name columns
    """

    def __init__(self, device_name: str = "generic"):
        self._name = device_name

    @property
    def name(self) -> str:
        return self._name

    def extract_data(self, payload: Dict[str, Any], command: str) -> pd.DataFrame:
        # Try to find data array
        data = self._find_data(payload)

        if not data or not isinstance(data, dict):
            return pd.DataFrame()

        # Get data array (try common keys)
        data_array = data.get("0") or data.get("data") or data.get("values") or []

        if not data_array:
            return pd.DataFrame()

        # Get schema
        schema = self.get_schema(command)

        # Apply column names
        n_cols = len(data_array[0]) if data_array else 0
        columns = schema.columns[:n_cols] if n_cols >= len(schema.columns) else schema.columns + [f"col_{i}" for i in range(n_cols - len(schema.columns))]

        return pd.DataFrame(data_array, columns=columns[:n_cols])

    def _find_data(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Navigate payload to find data dict."""
        if isinstance(payload, dict):
            # Try response.data path
            if "response" in payload:
                resp = payload["response"]
                if isinstance(resp, dict) and "data" in resp:
                    return resp["data"]
                return resp

            # Try direct data key
            if "data" in payload:
                return payload["data"]

        return None


def register_all():
    """Import and register all built-in adapters."""
    from adapters.first import FirstMachineAdapter
    from adapters.biologic import BiologicAdapter

    AdapterRegistry.register(FirstMachineAdapter())
    AdapterRegistry.register(BiologicAdapter())
