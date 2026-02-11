"""
Available Labware Resource

Resource that exposes available labware types for the First machine.
"""

import json
from puda_drivers import labware


async def get_available_labware_resource() -> str:
    """Returns a JSON object mapping labware names to their row/column information.
    
    Provides a dictionary of all labware types that are available for use
    with the First machine, along with their row and column information.
    
    Returns:
        str: JSON-formatted object mapping labware names to dictionaries with
        'wells' containing 'rows' and 'cols' lists.
    """
    labware_dict = labware.get_available_labware()
    # Format as {labware_name: {"wells": {"rows": [...], "cols": [...]}}}
    formatted_dict = {
        name: {"wells": {"rows": data["rows"], "cols": data["cols"]}}
        for name, data in labware_dict.items()
    }
    return json.dumps(formatted_dict, indent=2)

