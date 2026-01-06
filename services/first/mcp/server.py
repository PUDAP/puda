"""
MCP Server for First Machine Service

Provides tools for generating protocols and workflows for the First lab automation machine.
"""

import json
import os
import traceback
from typing import List, Dict, Any
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel
from openrouter import OpenRouter
from puda_drivers import labware

# Load environment variables from .env file
load_dotenv()

# Define port as an environment variable with default
PORT = int(os.getenv('FIRST_MCP_PORT', '8001'))

# Define model name as an environment variable with default
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', "minimax/minimax-m2")

# Initialize OpenRouter client
openrouter_client = OpenRouter(
    api_key=os.getenv('OPENROUTER_API_KEY'),
)

# Initialize FastMCP server
mcp = FastMCP(
    name="FirstMCP",
    version="0.1.0",
    instructions="This MCP server provides tools for generating protocols and workflows for the First machine.",
)


class ProtocolCommand(BaseModel):
    """Represents a single command in a protocol."""
    command_type: str
    params: Dict[str, Any]


class Protocol(BaseModel):
    """Represents a complete protocol for the First machine."""
    protocol_name: str
    author: str
    description: str
    commands: List[ProtocolCommand]

    def to_json_sequence(self) -> str:
        """Convert the protocol to JSON command sequence format for NATS.
        
        Returns a JSON array of command objects matching the format used in sample_routine.py:
        [
            {
                "command": "load_deck",
                "params": { "deck_layout": {...} }
            },
            {
                "command": "attach_tip",
                "params": { "slot": "A3", "well": "G8" }
            },
            ...
        ]
        """
        sequence = []
        
        # Convert all commands to JSON format
        for cmd in self.commands:
            command_obj = {
                "command": cmd.command_type,
                "params": cmd.params
            }
            sequence.append(command_obj)
        
        return json.dumps(sequence, indent=2)


def _get_available_commands_data() -> str:
    """Returns a JSON object describing all available First machine commands and their parameters."""
    commands_info = {
        "commands": [
            {
                "command": "startup",
                "description": "Start up the machine by connecting all controllers and initializing subsystems",
                "params": {}
            },
            {
                "command": "shutdown",
                "description": "Gracefully shut down the machine by disconnecting all controllers",
                "params": {}
            },
            {
                "command": "get_position",
                "description": "Get the current position of the machine (async, returns qubot and pipette positions)",
                "params": {}
            },
            {
                "command": "load_labware",
                "description": "Load a labware object into a slot",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')",
                    "labware_name": "str - Name of the labware class to load"
                }
            },
            {
                "command": "load_deck",
                "description": "Load multiple labware into the deck at once",
                "params": {
                    "deck_layout": "dict - Dictionary mapping slot names to labware names, e.g. {'C1': 'trash_bin', 'C2': 'polyelectric_8_wellplate_30000ul'}"
                }
            },
            {
                "command": "attach_tip",
                "description": "Attach a tip from a slot",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')",
                    "well": "str (optional) - Well name within the slot (e.g., 'A1' for a well in a tiprack)"
                }
            },
            {
                "command": "drop_tip",
                "description": "Drop a tip into a slot",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')",
                    "well": "str - Well name within the slot",
                    "height_from_bottom": "float (optional, default 0.0) - Height from bottom of well in mm"
                }
            },
            {
                "command": "aspirate_from",
                "description": "Aspirate a volume of liquid from a slot",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')",
                    "well": "str - Well name within the slot",
                    "amount": "int - Volume to aspirate in µL",
                    "height_from_bottom": "float (optional, default 0.0) - Height from bottom of well in mm"
                }
            },
            {
                "command": "dispense_to",
                "description": "Dispense a volume of liquid to a slot",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')",
                    "well": "str - Well name within the slot",
                    "amount": "int - Volume to dispense in µL",
                    "height_from_bottom": "float (optional, default 0.0) - Height from bottom of well in mm"
                }
            },
            {
                "command": "capture_image",
                "description": "Capture a single image from the camera",
                "params": {
                    "save": "bool (optional, default False) - If True, save the image to captures folder",
                    "filename": "str (optional) - Filename for the saved image"
                }
            },
            {
                "command": "start_video_recording",
                "description": "Start recording a video",
                "params": {
                    "filename": "str (optional) - Filename for the video",
                    "fps": "float (optional) - Frames per second (default 30.0)"
                }
            },
            {
                "command": "stop_video_recording",
                "description": "Stop recording a video",
                "params": {}
            },
            {
                "command": "record_video",
                "description": "Record a video for a specified duration",
                "params": {
                    "duration_seconds": "float - Duration of the video in seconds",
                    "filename": "str (optional) - Filename for the video",
                    "fps": "float (optional) - Frames per second (default 30.0)"
                }
            },
            {
                "command": "get_slot_origin",
                "description": "Get the origin coordinates of a slot",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')"
                }
            },
            {
                "command": "get_absolute_z_position",
                "description": "Get the absolute position for a slot (and optionally a well)",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')",
                    "well": "str (optional) - Well name within the slot"
                }
            },
            {
                "command": "get_absolute_a_position",
                "description": "Get the absolute A-axis position for a slot (and optionally a well)",
                "params": {
                    "slot": "str - Slot name (e.g., 'A1', 'B2')",
                    "well": "str (optional) - Well name within the slot"
                }
            }
        ]
    }
    return json.dumps(commands_info, indent=2)


@mcp.tool(
    name="get_available_commands",
    description="Get a list of all available commands for the First machine with their parameters"
)
async def get_available_commands() -> str:
    """Returns a JSON object describing all available First machine commands and their parameters."""
    return _get_available_commands_data()


@mcp.tool(
    name="get_available_labware",
    description="Get a list of all available labware types for the First machine"
)
async def get_available_labware() -> List[str]:
    """Returns a list of available labware names."""
    return labware.get_available_labware()


@mcp.tool(
    name="natural_language_to_protocol",
    description="Convert natural language instructions into a First machine protocol"
)
async def natural_language_to_commands(
    name: str,
    author: str,
    description: str,
    instructions: str
) -> str:
    """Convert natural language instructions into a First machine protocol."""
    try:
        # Create a prompt for the DeepSeek model to extract structured protocol information
        prompt = f"""
        You are an expert in creating First machine protocols. Convert the following natural language instructions into a structured JSON representation of a First machine protocol.
        
        Here's information about available labware types:
        - {labware.get_available_labware()}
        
        Here's information about available commands:
        - {_get_available_commands_data()}
        
        Instructions to convert:
        {instructions}
        
        Return your answer as a valid JSON object with the following structure:
        {{
            "name": "{name}",
            "author": "{author}",
            "description": "{description}",
            "commands": [
                {{
                    "command_type": "command_type",
                    "params": {{
                        "param1": "value1",
                        "param2": "value2"
                    }}
                }}
            ]
        }}
        """

        # Call the OpenRouter API
        response = openrouter_client.chat.send(
            model=OPENROUTER_MODEL,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        # Extract the JSON from the response
        json_content = response.choices[0].message.content
        
        return json_content
    except Exception as e:
        error_details = traceback.format_exc()
        return f"Error generating protocol: {str(e)}\n\nDetails: {error_details}."


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=PORT)

