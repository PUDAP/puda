"""
First Machine adapter for puda-data.

Handles data extraction from First machine / qubot payloads.

Payload structure:
{
    "response": {
        "data": {
            "0": [[potential, current, time, extra, flag], ...]
        }
    }
}
"""

from typing import Dict, Any
import pandas as pd

from adapters import DeviceAdapter
from registry import SchemaRegistry


class FirstMachineAdapter(DeviceAdapter):
    """Adapter for First machine (qubot) devices."""

    @property
    def name(self) -> str:
        return "first"

    def extract_data(self, payload: Dict[str, Any], command: str) -> pd.DataFrame:
        """
        Extract data from First machine payload.

        First machine stores data in: response.data."0"
        """
        # Navigate payload structure
        response = payload.get("response", {})
        data = response.get("data", {})

        # Get the data array (key "0" contains the measurement)
        data_array = data.get("0", [])

        if not data_array:
            return pd.DataFrame()

        # Get schema for this command
        schema = self.get_schema(command)

        # Determine column count and apply names
        n_cols = len(data_array[0]) if data_array else 0
        columns = schema.columns[:n_cols] if n_cols >= len(schema.columns) else [f"col_{i}" for i in range(n_cols)]

        df = pd.DataFrame(data_array, columns=columns[:n_cols])
        return df
