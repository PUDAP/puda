"""
puda-data Schema Registry

Central registry for data schemas across devices and measurement types.
Enables generalization beyond hardcoded column mappings.

Schema = {
    "columns": list of column names,
    "data_path": dotted path to data array in payload (e.g. "response.data.0"),
    "units": dict mapping column names to units,
    "primary_x": column name for x-axis in default plots,
    "primary_y": column name for y-axis in default plots,
}
"""

from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Schema:
    """Immutable schema definition for a measurement type."""
    columns: List[str]
    data_path: str = "response.data.0"
    units: Dict[str, str] = field(default_factory=dict)
    primary_x: str = ""
    primary_y: str = ""

    def __post_init__(self):
        if not self.primary_x and self.columns:
            object.__setattr__(self, 'primary_x', self.columns[0])
        if not self.primary_y and len(self.columns) > 1:
            object.__setattr__(self, 'primary_y', self.columns[1])


# Built-in schemas for common measurement types
BUILTIN_SCHEMAS: Dict[Tuple[str, str], Schema] = {
    # First machine schemas
    ("first", "CV"): Schema(
        columns=["potential", "current", "time", "extra", "flag"],
        data_path="response.data.0",
        units={"potential": "V", "current": "A", "time": "s"},
        primary_x="potential",
        primary_y="current",
    ),
    ("first", "OCV"): Schema(
        columns=["potential", "current", "time", "extra", "flag"],
        data_path="response.data.0",
        units={"potential": "V", "current": "A", "time": "s"},
        primary_x="time",
        primary_y="potential",
    ),
    ("first", "CA"): Schema(
        columns=["time", "current", "voltage", "extra", "flag"],
        data_path="response.data.0",
        units={"time": "s", "current": "A", "voltage": "V"},
        primary_x="time",
        primary_y="current",
    ),
    ("first", "PEIS"): Schema(
        columns=["frequency", "Z_real", "Z_imag", "phase", "flag"],
        data_path="response.data.0",
        units={"frequency": "Hz", "Z_real": "Ω", "Z_imag": "Ω", "phase": "rad"},
        primary_x="frequency",
        primary_y="Z_real",
    ),
    ("first", "GEIS"): Schema(
        columns=["frequency", "Z_real", "Z_imag", "phase", "flag"],
        data_path="response.data.0",
        units={"frequency": "Hz", "Z_real": "Ω", "Z_imag": "Ω", "phase": "rad"},
        primary_x="frequency",
        primary_y="Z_real",
    ),
    # Biologic machine schemas (different data path)
    ("biologic", "CV"): Schema(
        columns=["E", "I", "time", "Ewe", "flag"],
        data_path="response.data.0",
        units={"E": "V", "I": "A", "time": "s", "Ewe": "V"},
        primary_x="E",
        primary_y="I",
    ),
    ("biologic", "PEIS"): Schema(
        columns=["frequency", "Z_real", "Z_imag", "phase", "magnitude"],
        data_path="response.data.0",
        units={"frequency": "Hz", "Z_real": "Ω", "Z_imag": "Ω", "phase": "rad"},
        primary_x="Z_real",
        primary_y="-Z_imag",
    ),
}


class SchemaRegistry:
    """
    Registry for device/measurement schemas with auto-inference support.

    Usage:
        # Get schema for a device+command
        schema = SchemaRegistry.get("first", "CV")

        # Register a new schema
        SchemaRegistry.register("my_device", "CUSTOM", Schema(columns=[...]))

        # Auto-detect based on data structure
        schema = SchemaRegistry.detect(df, command_name="CV")
    """

    _schemas: Dict[Tuple[str, str], Schema] = {}
    _inferrers: Dict[str, Callable] = {}  # command_name -> inferrer function

    @classmethod
    def register(
        cls,
        device: str,
        command: str,
        schema: Schema,
    ) -> None:
        """Register a schema for a device+command pair."""
        cls._schemas[(device.lower(), command.upper())] = schema

    @classmethod
    def get(cls, device: str, command: str) -> Optional[Schema]:
        """Get schema for device+command, returns None if not found."""
        return cls._schemas.get((device.lower(), command.upper()))

    @classmethod
    def get_or_default(
        cls,
        device: str,
        command: str,
        fallback_columns: Optional[List[str]] = None,
    ) -> Schema:
        """Get schema or create a default based on column count."""
        schema = cls.get(device, command)
        if schema:
            return schema

        if fallback_columns:
            return Schema(columns=fallback_columns)

        # Auto-generate based on command type
        defaults = {
            "CV": ["potential", "current", "time", "extra", "flag"],
            "OCV": ["potential", "current", "time", "extra", "flag"],
            "CA": ["time", "current", "voltage", "extra", "flag"],
            "PEIS": ["frequency", "Z_real", "Z_imag", "phase", "flag"],
            "GEIS": ["frequency", "Z_real", "Z_imag", "phase", "flag"],
        }
        cols = defaults.get(command.upper(), [f"col_{i}" for i in range(5)])
        return Schema(columns=cols)

    @classmethod
    def register_inferrer(cls, command: str, inferrer: Callable[[Any], Schema]) -> None:
        """
        Register an auto-inference function for a command type.

        Args:
            command: Command name (e.g., "CV")
            inferrer: Function that takes raw data and returns a Schema
        """
        cls._inferrers[command.upper()] = inferrer

    @classmethod
    def detect(cls, raw_data: Any, command: str) -> Schema:
        """
        Auto-detect schema from raw data structure.

        Args:
            raw_data: Raw data (list of lists, DataFrame, etc.)
            command: Command name hint

        Returns:
            Schema with inferred columns
        """
        import pandas as pd

        # Get column count from first row
        if isinstance(raw_data, list) and raw_data:
            col_count = len(raw_data[0]) if raw_data[0] else 0
        elif isinstance(raw_data, pd.DataFrame):
            col_count = len(raw_data.columns)
        else:
            col_count = 0

        # Use registered inferrer if available
        if command.upper() in cls._inferrers:
            return cls._inferrers[command.upper()](raw_data)

        # Default inference: col_0, col_1, ...
        return Schema(columns=[f"col_{i}" for i in range(col_count)])

    @classmethod
    def list_registered(cls) -> List[Tuple[str, str]]:
        """List all registered device+command pairs."""
        return list(cls._schemas.keys())


# Initialize registry with built-in schemas
for (device, command), schema in BUILTIN_SCHEMAS.items():
    SchemaRegistry.register(device, command, schema)


# Built-in inferrer for CV (detects forward/backward from flag column)
def infer_cv_schema(raw_data) -> Schema:
    """Infer CV schema based on data characteristics."""
    import pandas as pd
    if isinstance(raw_data, pd.DataFrame):
        n_cols = len(raw_data.columns)
    elif isinstance(raw_data, list) and raw_data:
        n_cols = len(raw_data[0])
    else:
        n_cols = 5

    if n_cols >= 5:
        return Schema(
            columns=["potential", "current", "time", "extra", "flag"],
            units={"potential": "V", "current": "A", "time": "s"},
            primary_x="potential",
            primary_y="current",
        )
    return Schema(columns=[f"col_{i}" for i in range(n_cols)])


SchemaRegistry.register_inferrer("CV", infer_cv_schema)
