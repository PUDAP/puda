"""
Biologic adapter for puda-data.

Handles data extraction from Biologic potentiostat payloads.

Payload structure (similar to First):
{
    "response": {
        "data": {
            "0": [[E, I, time, Ewe, flag], ...]
        }
    }
}

Note: Biologic uses different column names (E, I, Ewe instead of potential, current)
but the payload structure is the same as First machine.
"""

from typing import Dict, Any
import pandas as pd

from adapters import DeviceAdapter
from registry import SchemaRegistry


class BiologicAdapter(DeviceAdapter):
    """Adapter for Biologic potentiostat devices."""

    @property
    def name(self) -> str:
        return "biologic"

    def extract_data(self, payload: Dict[str, Any], command: str) -> pd.DataFrame:
        """
        Extract data from Biologic payload.

        Biologic stores data in: response.data."0"
        Column names differ from First: E, I, time, Ewe, flag
        """
        # Navigate payload structure (same as First)
        response = payload.get("response", {})
        data = response.get("data", {})

        # Get the data array
        data_array = data.get("0", [])

        if not data_array:
            return pd.DataFrame()

        # Get schema for this command (biologic has its own schemas)
        schema = SchemaRegistry.get_or_default("biologic", command)

        # Determine column count and apply names
        n_cols = len(data_array[0]) if data_array else 0
        columns = schema.columns[:n_cols] if n_cols >= len(schema.columns) else [f"col_{i}" for i in range(n_cols)]

        df = pd.DataFrame(data_array, columns=columns[:n_cols])
        return df
