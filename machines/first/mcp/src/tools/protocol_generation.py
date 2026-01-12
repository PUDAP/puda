"""
Protocol Generation Tool

Tool for converting natural language instructions into machine commands.
"""

import traceback
from puda_drivers import labware
from ..utils.config import Config
from ..dependencies import get_openrouter_client
from ..resources.commands import get_available_commands_data


async def generate_machine_commands(instructions: str) -> str:
    """Generate machine commands from natural language instructions for the First machine.
    
    Takes natural language instructions and converts them into a structured JSON
    representation of a First machine protocol using AI.
    
    Args:
        instructions: Natural language description of the protocol to generate.
        
    Returns:
        str: JSON array of command objects representing the protocol.
    """
    try:
        # Create a prompt for the model to extract structured protocol information
        commands_json = get_available_commands_data()
        labware_lines = [f"{labware.StandardLabware(lw)}" for lw in labware.get_available_labware()]
        prompt = f"""
        You are an expert in creating First machine protocols. Convert the following natural language instructions into a structured JSON representation of a First machine protocol.
        
        Here's information about available labware types:
        {"\n".join(labware_lines)}
        
        Here's information about available commands:
        {commands_json}
        
        Instructions to convert:
        {instructions}
        
        Return your answer as a valid JSON array of command objects (not wrapped in a "commands" key):
        [
            {{
                "command": "command_type",
                "params": {{
                    "param1": "value1",
                    "param2": "value2"
                }}
            }},
            {{
                "command": "another_command",
                "params": {{
                    "param1": "value1"
                }}
            }}
        ]
        """

        # Get OpenRouter client from dependencies
        openrouter_client = get_openrouter_client()
        
        # Call the OpenRouter API
        response = openrouter_client.chat.send(
            model=Config.OPENROUTER_MODEL,
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

