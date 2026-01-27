# src/puda_drivers/labware/labware.py

import json
import inspect
from pathlib import Path
from typing import Dict, Any, List, Optional
from abc import ABC
from puda_drivers.core import Position


class StandardLabware(ABC):
    """
    Generic Parent Class for all Labware on a microplate
    """
    def __init__(self, labware_name: str):
        """
        Initialize the labware.
        Args:
            name: The name of the labware.
            rows: The number of rows in the labware.
            cols: The number of columns in the labware.
        """
        self._definition = self.load_definition(file_name=labware_name + ".json")
        self.name = self._definition.get("metadata", {}).get("displayName", "displayName not found")
        self._wells = self._definition.get("wells", {})

    @staticmethod
    def get_available_labware() -> List[str]:
        """
        Get all available labware names from JSON definition files.
        
        Returns:
            Sorted list of labware names (without .json extension) found in the labware directory.
        """
        labware_dir = Path(__file__).parent
        json_files = sorted(labware_dir.glob("*.json"))
        return [f.stem for f in json_files]

    def load_definition(self, file_name: str = "definition.json") -> Dict[str, Any]:
        """
        Load a definition.json file from the class's module directory.
        
        This method automatically finds the definition.json file in the
        same directory as the class that defines it.
        
        Args:
            file_name: Name of the definition file (default: "definition.json")
            
        Returns:
            Dictionary containing the labware definition
            
        Raises:
            FileNotFoundError: If the definition file doesn't exist
        """
        # Get the file path of the class that defines this method
        class_file = Path(inspect.getfile(self.__class__))
        definition_path = class_file.parent / file_name
        
        if not definition_path.exists():
            raise FileNotFoundError(
                f"Definition file '{file_name}' not found in {class_file.parent}"
            )
        
        with open(definition_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def __str__(self):
        """
        Return a string representation of the labware.
        """
        lines = [
            f"Labware name: {self.name}",
            f"Height in mm: {self.get_height()}",
            "Distances away from origin (0,0) for each well in mm"
        ]
        
        for well_id, well_data in self._wells.items():
            x, y, z = well_data.get("x"), well_data.get("y"), well_data.get("z")

            if x is None or y is None or z is None:
                raise KeyError(f"Well '{well_id}' has missing coordinates in labware definition")

            lines.append(f"Well {well_id}: x:{x}, y:{y}, z:{z}")
        return "\n".join(lines)

    @property
    def wells(self) -> List[str]:
        """
        Get a list of all well IDs in the labware.
        
        Returns:
            List of well identifiers (e.g., ["A1", "A2", "B1", ...])
        """
        return list(self._wells.keys())

    def get_well_position(self, well_id: str) -> Position:
        """
        Get the position of a well from definition.json.
        
        Args:
            well_id: Well identifier (e.g., "A1", "H12")
            
        Returns:
            Position with x, y, z coordinates
            
        Raises:
            KeyError: If well_id doesn't exist in the tip rack
        """
        # Validate location exists in JSON definition
        well_id_upper = well_id.upper()
        if well_id_upper not in self._wells:
            raise KeyError(f"Well '{well_id}' not found in tip rack definition")

        # Get the well data from the definition
        well_data = self._wells.get(well_id_upper, {})

        # Return position of the well (x, y are already center coordinates)
        return Position(
            x=well_data.get("x", 0.0),
            y=well_data.get("y", 0.0),
            z=well_data.get("z", 0.0),
        )

    def get_height(self, well_name: Optional[str] = None) -> float:
        """
        Get the height of the labware.

        Args:
            well_name: Optional well name within the labware (e.g., "A1" for a well in a tiprack)
                If not provided, the height of the labware is returned (zDimension).
        Returns:
            Height of the labware (zDimension) or the height of the well (z)
            
        Raises:
            KeyError: If dimensions or zDimension is not found in the definition, or if well_name is not found in the labware
        """
        dimensions = self._definition.get("dimensions")
        if dimensions is None:
            raise KeyError("'dimensions' not found in labware definition")
        
        if well_name:
            well_data = self._wells.get(well_name.upper(), {})
            if well_data is None:
                raise KeyError(f"Well '{well_name}' not found in labware definition")
            return well_data.get("z")
        else:
            if "zDimension" not in dimensions:
                raise KeyError("'zDimension' not found in labware dimensions")
            return dimensions["zDimension"]

    def get_insert_depth(self) -> float:
        """
        Get the insert depth of the labware. This should be added to all labware definitions.
        
        insert_depth represents the maximum internal Z-axis clearance of the
        labware. It is calculated as the absolute difference between the Top
        Plane (the highest point of the well opening) and the Internal Floor
        (the physical bottom of the well).
        
        Top of Labware (Z = 0 reference)
              │      │
        ┌─────┴──────┴─────┐  <─── Opening
        │                  │
        │      SPACE       │  }
        │    AVAILABLE     │  }
        │       FOR        │  }  insert_depth
        │    INSERTION     │  }  (e.g., 40mm)
        │                  │  }
        └──────┬───────────┘
               │
        Bottom of Well (Limit)
        
        Returns:
            Insert depth of the labware
            
        Raises:
            KeyError: If insert_depth is not found in the definition
        """
        if "insert_depth" not in self._definition:
            raise KeyError("'insert_depth' not found in labware definition")
        
        return self._definition["insert_depth"]