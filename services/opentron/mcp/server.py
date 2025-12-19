import asyncio
from fastmcp import FastMCP
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel
#from opentrons import protocol_api
import json
import re
import os
import pandas as pd
from dotenv import load_dotenv
from llm_config import get_llm, parse_thinking_from_response
import csv
import requests
import time
import pprint

# Load environment variables from .env file
load_dotenv()

# Define port as an environment variable with default
PORT = int(os.getenv('OPENTRON_PORT', 8002))

# Initialize FastMCP server on port 8002
mcp = FastMCP(
    "OpenTron Protocol Provider"
)

# Initialize LLM from config
model = get_llm()

class ProtocolCommand(BaseModel):
    command_type: str
    params: Dict[str, Any]

class Protocol(BaseModel):
    protocol_name: str
    author: str
    description: str
    robot_type: str
    api_level: str
    commands: List[ProtocolCommand]

    def to_python_code(self) -> str:
        """Convert the protocol to Python code that can be run on OpenTron"""
        import json
        
        # Create metadata as proper Python dict
        metadata = {
            "protocolName": self.protocol_name,
            "author": self.author,
            "description": self.description,
        }
        
        requirements = {
            "robotType": self.robot_type,
            "apiLevel": self.api_level
        }
        
        # Custom pretty-print for Python dict with double quotes, no escaping
        def dict_to_py_str(d, indent=4):
            lines = ["{"]
            for i, (k, v) in enumerate(d.items()):
                comma = "," if i < len(d) - 1 else ""
                lines.append(f'{" "*indent}"{k}": "{v}"{comma}')
            lines.append("}")
            return "\n".join(lines)

        metadata_str = dict_to_py_str(metadata)
        requirements_str = dict_to_py_str(requirements)
        
        code = f"""from opentrons import protocol_api
        

# metadata
metadata = {metadata_str}

# requirements
requirements = {requirements_str}

# protocol run function
def run(protocol: protocol_api.ProtocolContext):
    # Initialize variables to store labware and instruments
    labware = {{}}
    pipettes = {{}}
    
"""
        
        data_var = None
        data_file = None
        data_read_code = ""
        
        # Helpers for height/offset handling in generated code
        def _get_first(params: Dict[str, Any], keys: List[str], default=None):
            for k in keys:
                if k in params:
                    return params[k]
            return default
        
        def _build_location_expr(labware_name: str, well_expr: str, ref: Optional[str], offset: Optional[Any]) -> str:
            base = f"labware[{repr(labware_name)}][{well_expr}]"
            if ref:
                ref_lower = str(ref).lower()
                if ref_lower in ["top", "bottom"]:
                    # Offset may be numeric or dynamic (e.g., "row['offset']")
                    if offset is None or (isinstance(offset, str) and not offset.strip()):
                        return f"{base}.{ref_lower}()"
                    else:
                        if isinstance(offset, str) and offset.strip().startswith("row["):
                            return f"{base}.{ref_lower}({offset})"
                        else:
                            try:
                                off_val = float(offset)
                                return f"{base}.{ref_lower}({off_val})"
                            except Exception:
                                return f"{base}.{ref_lower}()"
            return base
        
        # First pass: generate code for all commands, including loop handling
        for i, cmd in enumerate(self.commands):
            try:
                if cmd.command_type == "read_csv_file" or cmd.command_type == "read_csv":
                    if 'file_path' in cmd.params:
                        data_var = 'data'
                        data_file = cmd.params['file_path']
                        # Check if csv_data is provided (inline data)
                        if 'csv_data' in cmd.params:
                            # Embed the data directly in the code with proper formatting
                            csv_data = cmd.params['csv_data']
                            import json
                            csv_data_str = json.dumps(csv_data, indent=4)
                            data_read_code = f"    # CSV data embedded directly in the protocol\n    {data_var} = {csv_data_str}\n\n"
                        else:
                            # Fall back to file reading
                            data_read_code = f"    import pandas as pd\n    {data_var} = pd.read_csv('{data_file}').to_dict(orient='records')\n\n"
                    continue  # Don't process this command further here
                elif (cmd.command_type == "loop" and 'for' in cmd.params and 'commands' in cmd.params) or (cmd.command_type == "loop_over_csv" and 'commands' in cmd.params):
                    # Always use 'for row in data:' for CSV loops
                    code += f"    for row in data:\n"
                    for subcmd in cmd.params['commands']:
                        # Handle subcommands directly without creating a new protocol
                        if isinstance(subcmd, dict):
                            subcmd_obj = ProtocolCommand(**subcmd)
                        else:
                            subcmd_obj = subcmd
                        
                        # Generate individual command code with proper indentation
                        if subcmd_obj.command_type == "pick_up_tip":
                            code += f"        pipettes['{subcmd_obj.params['pipette']}'].pick_up_tip()\n"
                        elif subcmd_obj.command_type == "aspirate":
                            volume_param = subcmd_obj.params['volume']
                            if isinstance(volume_param, str) and volume_param.strip().startswith("row["):
                                volume_str = volume_param
                            else:
                                volume_str = str(float(volume_param))
                            
                            well_param = subcmd_obj.params.get('well', '')
                            if isinstance(well_param, str) and well_param.strip().startswith("row["):
                                well_str = well_param
                            else:
                                well_str = f"'{well_param}'"
                            # Height control
                            asp_ref = _get_first(subcmd_obj.params, [
                                'aspirate_ref', 'aspirate_position', 'aspirate_height_ref', 'position', 'ref'
                            ])
                            asp_off = _get_first(subcmd_obj.params, [
                                'aspirate_offset', 'aspirate_height', 'aspirate_z_offset', 'offset', 'z_offset'
                            ])
                            loc_expr = _build_location_expr(subcmd_obj.params['labware'], well_str, asp_ref, asp_off)
                            code += f"        pipettes['{subcmd_obj.params['pipette']}'].aspirate({volume_str}, {loc_expr})\n"
                        elif subcmd_obj.command_type == "dispense":
                            volume_param = subcmd_obj.params['volume']
                            if isinstance(volume_param, str) and volume_param.strip().startswith("row["):
                                volume_str = volume_param
                            else:
                                volume_str = str(float(volume_param))
                            
                            well_param = subcmd_obj.params.get('well', '')
                            if isinstance(well_param, str) and well_param.strip().startswith("row["):
                                well_str = well_param
                            else:
                                well_str = f"'{well_param}'"
                            # Height control
                            dsp_ref = _get_first(subcmd_obj.params, [
                                'dispense_ref', 'dispense_position', 'dispense_height_ref', 'position', 'ref'
                            ])
                            dsp_off = _get_first(subcmd_obj.params, [
                                'dispense_offset', 'dispense_height', 'dispense_z_offset', 'offset', 'z_offset'
                            ])
                            loc_expr = _build_location_expr(subcmd_obj.params['labware'], well_str, dsp_ref, dsp_off)
                            code += f"        pipettes['{subcmd_obj.params['pipette']}'].dispense({volume_str}, {loc_expr})\n"
                        elif subcmd_obj.command_type == "drop_tip":
                            code += f"        pipettes['{subcmd_obj.params['pipette']}'].drop_tip()\n"
                        elif subcmd_obj.command_type == "move_to":
                            well_param = subcmd_obj.params.get('well', '')
                            if isinstance(well_param, str) and well_param.strip().startswith("row["):
                                well_str = well_param
                            else:
                                well_str = f"'{well_param}'"
                            # Height control - provide default if not specified
                            move_ref = _get_first(subcmd_obj.params, [
                                'move_ref', 'move_position', 'move_height_ref', 'position', 'ref'
                            ])
                            move_off = _get_first(subcmd_obj.params, [
                                'move_offset', 'move_height', 'move_z_offset', 'offset', 'z_offset'
                            ])
                            
                            # If no height reference specified, default to top() for safety
                            if move_ref is None:
                                move_ref = "top"
                                if move_off is None:
                                    move_off = 50  # Default 50mm above top for safe positioning
                            
                            loc_expr = _build_location_expr(subcmd_obj.params['labware'], well_str, move_ref, move_off)
                            code += f"        pipettes['{subcmd_obj.params['pipette']}'].move_to({loc_expr})\n"
                        elif subcmd_obj.command_type == "comment":
                            code += f"        # {subcmd_obj.params['text']}\n"
                        elif subcmd_obj.command_type == "delay":
                            # Support seconds/minutes and optional pipette target
                            seconds = _get_first(subcmd_obj.params, ['seconds'])
                            minutes = _get_first(subcmd_obj.params, ['minutes'])
                            message = _get_first(subcmd_obj.params, ['message', 'text', 'comment'])
                            pipette = _get_first(subcmd_obj.params, ['pipette'])
                            if message:
                                code += f"        protocol.comment({repr(str(message))})\n"
                            if pipette:
                                args = []
                                if minutes is not None:
                                    args.append(f"minutes={minutes}")
                                if seconds is not None:
                                    args.append(f"seconds={seconds}")
                                arg_str = ", ".join(args) if args else "seconds=1"
                                code += f"        pipettes['{pipette}'].delay({arg_str})\n"
                            else:
                                if minutes is not None and seconds is not None:
                                    code += f"        protocol.delay(minutes={minutes}, seconds={seconds})\n"
                                elif minutes is not None:
                                    code += f"        protocol.delay(minutes={minutes})\n"
                                elif seconds is not None:
                                    code += f"        protocol.delay(seconds={seconds})\n"
                                else:
                                    code += f"        protocol.delay(seconds=1)\n"
                elif cmd.command_type == "load_labware":
                    code += f"    # Load labware\n"
                    # Check for required parameters
                    if 'name' not in cmd.params or 'labware_type' not in cmd.params or 'location' not in cmd.params:
                        code += f"    # Error: Missing required parameter for load_labware at command {i+1}\n"
                        code += f"    # Required: name, labware_type, location\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                        
                    code += f"    labware[{repr(cmd.params['name'])}] = protocol.load_labware(\n"
                    code += f"        {repr(cmd.params['labware_type'])}, location={repr(cmd.params['location'])}\n"
                    code += f"    )\n\n"
                
                elif cmd.command_type == "load_instrument":
                    code += f"    # Load pipette\n"
                    # Check for required parameters
                    if 'name' not in cmd.params or 'instrument_type' not in cmd.params or 'mount' not in cmd.params:
                        code += f"    # Error: Missing required parameter for load_instrument at command {i+1}\n"
                        code += f"    # Required: name, instrument_type, mount\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                        
                    tip_racks = cmd.params.get('tip_racks', [])
                    tip_racks_str = ", ".join([f"labware[{repr(rack)}]" for rack in tip_racks])
                    code += f"    pipettes[{repr(cmd.params['name'])}] = protocol.load_instrument(\n"
                    code += f"        {repr(cmd.params['instrument_type'])},\n"
                    code += f"        mount={repr(cmd.params['mount'])},\n"
                    code += f"        tip_racks=[{tip_racks_str}]\n"
                    code += f"    )\n\n"
                
                elif cmd.command_type == "pick_up_tip":
                    code += f"    # Pick up tip\n"
                    # Check for required parameters
                    if 'pipette' not in cmd.params:
                        code += f"    # Error: Missing required parameter for pick_up_tip at command {i+1}\n"
                        code += f"    # Required: pipette\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                        
                    if 'well' in cmd.params and 'labware' in cmd.params:
                        code += f"    pipettes['{cmd.params['pipette']}'].pick_up_tip(labware['{cmd.params['labware']}']['{cmd.params['well']}'])\n\n"
                    else:
                        code += f"    pipettes['{cmd.params['pipette']}'].pick_up_tip()\n\n"
                
                elif cmd.command_type == "aspirate":
                    code += f"    # Aspirate\n"
                    # Check for required parameters
                    if 'pipette' not in cmd.params or 'volume' not in cmd.params:
                        code += f"    # Error: Missing required parameter for aspirate at command {i+1}\n"
                        code += f"    # Required: pipette, volume\n"
                        code += f"    # Recommended: labware, well (if labware and well are not provided, aspirate from the current position)\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                    
                    pipette_name = cmd.params['pipette']
                    volume_param = cmd.params['volume']
                    # If volume_param is a string and starts with row[, insert as-is
                    if isinstance(volume_param, str) and volume_param.strip().startswith("row["):
                        volume_str = volume_param
                    else:
                        volume_str = str(float(volume_param))
                    
                    # Handle dynamic well parameter
                    well_param = cmd.params.get('well', '')
                    if isinstance(well_param, str) and well_param.strip().startswith("row["):
                        well_str = well_param
                    else:
                        well_str = f"'{well_param}'"
                    
                    # Check for labware and well parameters
                    if 'labware' not in cmd.params or 'well' not in cmd.params:
                        code += f"    # Error: Missing labware or well parameter for aspirate at command {i+1}\n"
                        code += f"    # Required: labware, well\n"
                        code += f"    pipettes['{cmd.params['pipette']}'].aspirate({volume_str})\n\n"
                    else:
                        asp_ref = _get_first(cmd.params, [
                            'aspirate_ref', 'aspirate_position', 'aspirate_height_ref', 'position', 'ref'
                        ])
                        asp_off = _get_first(cmd.params, [
                            'aspirate_offset', 'aspirate_height', 'aspirate_z_offset', 'offset', 'z_offset'
                        ])
                        loc_expr = _build_location_expr(cmd.params['labware'], well_str, asp_ref, asp_off)
                        code += f"    pipettes['{cmd.params['pipette']}'].aspirate({volume_str}, {loc_expr})\n\n"
                
                elif cmd.command_type == "dispense":
                    code += f"    # Dispense\n"
                    # Check for required parameters
                    if 'pipette' not in cmd.params or 'volume' not in cmd.params:
                        code += f"    # Error: Missing required parameter for dispense at command {i+1}\n"
                        code += f"    # Required: pipette, volume\n"
                        code += f"    # Recommended: labware, well (if labware and well are not provided, dispense at the current position)\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                    
                    pipette_name = cmd.params['pipette']
                    volume_param = cmd.params['volume']
                    if isinstance(volume_param, str) and volume_param.strip().startswith("row["):
                        volume_str = volume_param
                    else:
                        volume_str = str(float(volume_param))
                    
                    # Handle dynamic well parameter
                    well_param = cmd.params.get('well', '')
                    if isinstance(well_param, str) and well_param.strip().startswith("row["):
                        well_str = well_param
                    else:
                        well_str = f"'{well_param}'"
                    
                    if 'labware' not in cmd.params or 'well' not in cmd.params:
                        code += f"    # Error: Missing labware or well parameter for dispense at command {i+1}\n"
                        code += f"    # Required: labware, well\n"
                        code += f"    pipettes['{cmd.params['pipette']}'].dispense({volume_str})\n\n"
                    else:
                        dsp_ref = _get_first(cmd.params, [
                            'dispense_ref', 'dispense_position', 'dispense_height_ref', 'position', 'ref'
                        ])
                        dsp_off = _get_first(cmd.params, [
                            'dispense_offset', 'dispense_height', 'dispense_z_offset', 'offset', 'z_offset'
                        ])
                        loc_expr = _build_location_expr(cmd.params['labware'], well_str, dsp_ref, dsp_off)
                        code += f"    pipettes['{cmd.params['pipette']}'].dispense({volume_str}, {loc_expr})\n\n"
                
                elif cmd.command_type == "drop_tip":
                    code += f"    # Drop tip\n"
                    # Check for required parameters
                    if 'pipette' not in cmd.params:
                        code += f"    # Error: Missing required parameter for drop_tip at command {i+1}\n"
                        code += f"    # Required: pipette\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                        
                    if 'well' in cmd.params and 'labware' in cmd.params:
                        code += f"    pipettes['{cmd.params['pipette']}'].drop_tip(labware['{cmd.params['labware']}']['{cmd.params['well']}'])\n\n"
                    else:
                        code += f"    pipettes['{cmd.params['pipette']}'].drop_tip()\n\n"
                
                elif cmd.command_type == "comment":
                    # Check for required parameters
                    if 'text' not in cmd.params:
                        code += f"    # Error: Missing 'text' parameter for comment at command {i+1}\n\n"
                        continue
                        
                    code += f"    # {cmd.params['text']}\n\n"
                
                elif cmd.command_type == "delay":
                    code += f"    # Delay\n"
                    # Support seconds or minutes and optional pipette target
                    seconds = _get_first(cmd.params, ['seconds'])
                    minutes = _get_first(cmd.params, ['minutes'])
                    message = _get_first(cmd.params, ['message', 'text', 'comment'])
                    pipette = _get_first(cmd.params, ['pipette'])
                    if message:
                        code += f"    protocol.comment({repr(str(message))})\n"
                    if pipette:
                        args = []
                        if minutes is not None:
                            args.append(f"minutes={minutes}")
                        if seconds is not None:
                            args.append(f"seconds={seconds}")
                        arg_str = ", ".join(args) if args else "seconds=1"
                        code += f"    pipettes['{pipette}'].delay({arg_str})\n\n"
                    else:
                        if minutes is not None and seconds is not None:
                            code += f"    protocol.delay(minutes={minutes}, seconds={seconds})\n\n"
                        elif minutes is not None:
                            code += f"    protocol.delay(minutes={minutes})\n\n"
                        elif seconds is not None:
                            code += f"    protocol.delay(seconds={seconds})\n\n"
                        else:
                            code += f"    protocol.delay(seconds=1)\n\n"
                
                elif cmd.command_type == "move_to":
                    code += f"    # Move to location\n"
                    # Check for required parameters
                    if 'pipette' not in cmd.params or 'labware' not in cmd.params or 'well' not in cmd.params:
                        code += f"    # Error: Missing required parameter for move_to at command {i+1}\n"
                        code += f"    # Required: pipette, labware, well\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                    
                    # Handle dynamic well parameter
                    well_param = cmd.params.get('well', '')
                    if isinstance(well_param, str) and well_param.strip().startswith("row["):
                        well_str = well_param
                    else:
                        well_str = f"'{well_param}'"
                    
                    # Height control - provide default if not specified
                    move_ref = _get_first(cmd.params, [
                        'move_ref', 'move_position', 'move_height_ref', 'position', 'ref'
                    ])
                    move_off = _get_first(cmd.params, [
                        'move_offset', 'move_height', 'move_z_offset', 'offset', 'z_offset'
                    ])
                    
                    # If no height reference specified, default to top() for safety
                    if move_ref is None:
                        move_ref = "top"
                        if move_off is None:
                            move_off = 10  # Default 10mm above top for safe positioning
                    
                    loc_expr = _build_location_expr(cmd.params['labware'], well_str, move_ref, move_off)
                    code += f"    pipettes['{cmd.params['pipette']}'].move_to({loc_expr})\n\n"
                
                elif cmd.command_type == "transfer":
                    code += f"    # Transfer\n"
                    # Check for required parameters
                    if 'pipette' not in cmd.params or 'volume' not in cmd.params or 'source_labware' not in cmd.params or 'source_well' not in cmd.params or 'dest_labware' not in cmd.params or 'dest_well' not in cmd.params:
                        code += f"    # Error: Missing required parameter for transfer at command {i+1}\n"
                        code += f"    # Required: pipette, volume, source_labware, source_well, dest_labware, dest_well\n"
                        code += f"    # Received: {cmd.params}\n\n"
                        continue
                    
                    # Determine max volume based on pipette type
                    pipette_name = cmd.params['pipette']
                    volume = float(cmd.params['volume'])
                    pipette_max_vol = 0
                    
                    if 'p1000' in pipette_name:
                        pipette_max_vol = 1000
                    elif 'p300' in pipette_name:
                        pipette_max_vol = 300
                    elif 'p20' in pipette_name:
                        pipette_max_vol = 20
                    else:
                        # Default to p300 if pipette type is unknown
                        pipette_max_vol = 300
                    
                    # Build source/destination location with optional top/bottom offsets
                    src_ref = _get_first(cmd.params, ['source_ref', 'source_position', 'source_height_ref'])
                    src_off = _get_first(cmd.params, ['source_offset', 'source_height', 'source_z_offset'])
                    dst_ref = _get_first(cmd.params, ['dest_ref', 'dest_position', 'dest_height_ref'])
                    dst_off = _get_first(cmd.params, ['dest_offset', 'dest_height', 'dest_z_offset'])
                    source_expr = _build_location_expr(cmd.params['source_labware'], f"'{cmd.params['source_well']}'", src_ref, src_off)
                    dest_expr = _build_location_expr(cmd.params['dest_labware'], f"'{cmd.params['dest_well']}'", dst_ref, dst_off)

                    # For volumes within pipette capacity, use transfer directly
                    if volume <= pipette_max_vol:
                        code += f"    pipettes['{pipette_name}'].transfer({volume}, {source_expr}, {dest_expr})\n\n"
                    else:
                        # For large volumes, implement a loop
                        iterations = int(volume // pipette_max_vol)
                        remainder = volume % pipette_max_vol
                        
                        code += f"    # Handling large volume transfer ({volume} µl) with multiple iterations\n"
                        
                        if iterations > 0:
                            code += f"    # Transferring {iterations} full pipette volumes\n"
                            code += f"    for _ in range({iterations}):\n"
                            code += f"        pipettes['{pipette_name}'].transfer({pipette_max_vol}, {source_expr}, {dest_expr}, new_tip='once')\n"
                        
                        if remainder > 0:
                            code += f"    # Transferring remaining volume ({remainder} µl)\n"
                            code += f"    pipettes['{pipette_name}'].transfer({remainder}, {source_expr}, {dest_expr}, new_tip='once')\n\n"
                
                elif cmd.command_type == "table_transfer":
                    code += "    import pandas as pd\n"
                    code += f"    data = pd.DataFrame({json.dumps(cmd.params['data'])})\n"
                    code += f"    for i in range(len(data)):\n"
                    code += f"        pipettes['{cmd.params['pipette']}'].pick_up_tip()\n"
                    # Optional global height controls for table-driven transfer
                    t_asp_ref = _get_first(cmd.params, ['aspirate_ref', 'aspirate_position', 'aspirate_height_ref'])
                    t_asp_off = _get_first(cmd.params, ['aspirate_offset', 'aspirate_height', 'aspirate_z_offset'])
                    t_dsp_ref = _get_first(cmd.params, ['dispense_ref', 'dispense_position', 'dispense_height_ref'])
                    t_dsp_off = _get_first(cmd.params, ['dispense_offset', 'dispense_height', 'dispense_z_offset'])
                    src_expr = f"labware['{cmd.params['labware']}'][data.loc[i, 'source']]"
                    dst_expr = f"labware['{cmd.params['labware']}'][data.loc[i, 'destination']]"
                    if t_asp_ref:
                        ref = str(t_asp_ref).lower()
                        if t_asp_off is None:
                            src_expr = f"{src_expr}.{ref}()"
                        else:
                            src_expr = f"{src_expr}.{ref}({t_asp_off})"
                    if t_dsp_ref:
                        ref = str(t_dsp_ref).lower()
                        if t_dsp_off is None:
                            dst_expr = f"{dst_expr}.{ref}()"
                        else:
                            dst_expr = f"{dst_expr}.{ref}({t_dsp_off})"
                    code += f"        pipettes['{cmd.params['pipette']}'].aspirate(data.loc[i, 'volume'], {src_expr})\n"
                    code += f"        pipettes['{cmd.params['pipette']}'].dispense(data.loc[i, 'volume'], {dst_expr})\n"
                    code += f"        pipettes['{cmd.params['pipette']}'].drop_tip()\n\n"
                
                else:
                    code += f"    # Unknown command type: {cmd.command_type} at command {i+1}\n\n"
            except Exception as e:
                code += f"    # Error processing command {i+1} ({cmd.command_type}): {str(e)}\n\n"
        
        # Insert DataFrame read code after labware/instrument setup
        if data_read_code:
            # Find where labware/instrument setup ends and insert CSV read code there
            lines = code.split('\n')
            insert_index = len(lines)
            
            # Find the last load_instrument or load_labware line
            for i, line in enumerate(lines):
                if 'load_instrument' in line or 'load_labware' in line:
                    insert_index = i + 2  # After the closing parenthesis and empty line
            
            # Insert the CSV reading code
            lines.insert(insert_index, data_read_code.rstrip())
            code = '\n'.join(lines)
        
        # Sanitize: replace any accidental df.loc[i, 'col'] with row['col']
        code = re.sub(r"df\.loc\[i, *'([^']+)'\]", r"row['\1']", code)
        return code

# The parse_natural_language function has been replaced by DeepSeek LLM integration
# This comment is kept as a placeholder to maintain code structure

@mcp.tool(
    name="create_protocol",
    description="Creates an OpenTron protocol with the specified parameters"
)
async def create_protocol(
    protocol_name: str,
    author: str,
    description: str,
    robot_type: str = "OT-2",
    api_level: Union[str, float] = "2.23",
    commands: str = "[]"
) -> str:
    """Creates an OpenTron protocol with the specified parameters."""
    try:
        # Parse commands JSON
        commands_list = json.loads(commands)
        
        # Create protocol object
        protocol = Protocol(
            protocol_name=protocol_name,
            author=author,
            description=description,
            robot_type=robot_type,
            api_level=str(api_level),  # Ensure string conversion
            commands=[ProtocolCommand(**cmd) for cmd in commands_list]
        )
        
        # Generate Python code
        python_code = protocol.to_python_code()
        
        return python_code
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"Error generating protocol: {str(e)}\n\nDetails: {error_details}"

@mcp.tool(
    name="read_csv_file",
    description="Reads a CSV file from the given file path and returns the data as a list of dictionaries."
)
async def read_csv_to_dataframe(file_path: str) -> list:
    """
    Reads a CSV file and returns the data as a list of dictionaries (one per row).
    Args:
        file_path (str): Path to the CSV file.
    Returns:
        list: List of dictionaries representing the CSV rows.
    """
    df = pd.read_csv(file_path)
    print(df)
    return df.to_dict(orient='records')

@mcp.tool(
    name="csv_to_list_of_dataframes",
    description="Reads a CSV file and returns a list of DataFrames, each containing a single row from the CSV. Returns as a list of dicts for serialization."
)
async def csv_to_list_of_dataframes(file_path: str) -> list:
    """
    Reads a CSV file and returns a list of DataFrames, each containing a single row, serialized as dicts.
    Args:
        file_path (str): Path to the CSV file.
    Returns:
        list: List of dicts, each representing a row from the CSV.
    """
    df = pd.read_csv(file_path)
    list_of_dfs = [row.to_frame().T for _, row in df.iterrows()]
    print(list_of_dfs)
    return [d.to_dict(orient='records')[0] for d in list_of_dfs]

@mcp.tool(
    name="run_csv_protocol",
    description="Run the csv protocol using DataFrame created"
)

async def run_csv_protocol(file_path, protocol, pipette, water_well, mixing_plate, aspirate_depth, dispense_height):
    """
    Reads a CSV file, appends the data as a DataFrame, and performs aspirate and dispense operations for each row.
    Args:
        file_path (str): Path to the CSV file.
        protocol: The Opentrons protocol context.
        pipette: The pipette object (e.g., protocol.load_instrument(...)).
        water_well: The source labware (e.g., protocol.load_labware(...)).
        mixing_plate: The destination labware (e.g., protocol.load_labware(...)).
        aspirate_depth (float): The aspirate depth for the pipette.
        dispense_height (float): The dispense height for the pipette.
    """
    import pandas as pd
    df = pd.read_csv(file_path)
    for i in range(len(df)):
        pipette.pick_up_tip()
        pipette.aspirate(float(df.loc[i, 'amt']), water_well[df.loc[i, 'src']].top(aspirate_depth), rate=1.0)
        pipette.dispense(float(df.loc[i, 'amt']), mixing_plate[df.loc[i, 'des']].top(dispense_height), rate=1.0)
        pipette.drop_tip()

@mcp.tool(
    name="opentron_csv_to_protocol",
    description="Converts CSV data directly into an OpenTron protocol"
)
async def opentron_csv_to_protocol(
    csv_data_list: list,
    protocol_name: str = "CSV Protocol",
    author: str = "User",
    description: str = "Auto-generated from CSV data",
    robot_type: str = "OT-2",
    api_level: Union[str, float] = "2.23"
) -> str:
    """Converts CSV data directly into an OpenTron protocol with simplified approach."""
    try:
        if not csv_data_list:
            return "Error: Empty CSV data provided"
        
        # Validate CSV data structure
        if not isinstance(csv_data_list, list) or len(csv_data_list) == 0:
            return "Error: CSV data must be a non-empty list"
        
        sample_row = csv_data_list[0]
        if not isinstance(sample_row, dict):
            return f"Error: CSV rows must be dictionaries, received {type(sample_row)}"
        
        columns = list(sample_row.keys())
        
        # Determine column mappings
        volume_col = 'volume'
        source_col = 'source_well'
        dest_col = 'dest_well'
        
        for col in columns:
            if 'volume' in col.lower() or 'amount' in col.lower():
                volume_col = col
            elif 'source' in col.lower():
                source_col = col
            elif 'dest' in col.lower() or 'destination' in col.lower():
                dest_col = col
        
        # Generate simple, clean protocol code
        import json
        csv_data_json = json.dumps(csv_data_list, indent=4)
        
        protocol_code = f'''from opentrons import protocol_api

# metadata
metadata = {{
    "protocolName": "{protocol_name}",
    "author": "{author}",
    "description": "{description}"
}}

# requirements
requirements = {{
    "robotType": "{robot_type}",
    "apiLevel": "{api_level}"
}}

def run(protocol: protocol_api.ProtocolContext):
    # Load labware
    plate = protocol.load_labware("corning_96_wellplate_360ul_flat", 1)
    tiprack = protocol.load_labware("opentrons_96_tiprack_300ul", 2)
    reservoir = protocol.load_labware("nest_12_reservoir_15ml", 3)
    
    # Load pipette
    p300 = protocol.load_instrument(
        "p300_single",
        mount="right",
        tip_racks=[tiprack]
    )
    
    # CSV data
    data = {csv_data_json}
    
    # Process each row
    for row in data:
        p300.pick_up_tip()
        
        # Get values from row
        volume = float(row.get("{volume_col}", 100))
        source_well = row.get("{source_col}", "A1")
        dest_well = row.get("{dest_col}", "B1")
        
        # Perform transfer
        p300.aspirate(volume, reservoir[source_well])
        p300.dispense(volume, plate[dest_well])
        p300.drop_tip()
'''
        
        # Validate syntax
        try:
            compile(protocol_code, '<string>', 'exec')
        except SyntaxError as e:
            return f"Syntax Error: {e.msg} at line {e.lineno}: {e.text}"
        
        return protocol_code
    
    except Exception as e:
        return f"Error generating CSV protocol: {str(e)}"

@mcp.tool(
    name="table_transfer_protocol",
    description="Creates an OpenTron protocol from a table of transfer instructions (source, destination, volume)."
)
async def table_transfer_protocol(
    protocol_name: str,
    author: str,
    description: str,
    robot_type: str = "OT-2",
    api_level: Union[str, float] = "2.23",
    data: list = None,
    pipette: str = "p300",
    labware: str = "plate"
) -> str:
    """
    Creates an OpenTron protocol from a table of transfer instructions.
    Args:
        protocol_name (str): Name of the protocol.
        author (str): Author name.
        description (str): Protocol description.
        robot_type (str): Robot type (default OT-2).
        api_level (str|float): API level (default 2.22).
        data (list): List of dicts with keys 'source', 'destination', 'volume'.
        pipette (str): Pipette name (default p300).
        labware (str): Labware name (default plate).
    Returns:
        str: Generated Python protocol code.
    """
    try:
        if data is None:
            return "Error: 'data' parameter (list of transfer dicts) is required."
        commands = [
            {
                "command_type": "table_transfer",
                "params": {
                    "data": data,
                    "pipette": pipette,
                    "labware": labware
                }
            }
        ]
        protocol = Protocol(
            protocol_name=protocol_name,
            author=author,
            description=description,
            robot_type=robot_type,
            api_level=str(api_level),
            commands=[ProtocolCommand(**cmd) for cmd in commands]
        )
        python_code = protocol.to_python_code()
        return python_code
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"Error generating protocol: {str(e)}\n\nDetails: {error_details}"

@mcp.tool(
    name="opentron_natural_language_to_protocol",
    description="Converts natural language instructions into an OpenTron protocol using DeepSeek LLM"
)
async def opentron_natural_language_to_protocol(
    instructions: str,
    protocol_name: str = "Generated Protocol",
    author: str = "User",
    description: str = "Auto-generated from natural language",
    robot_type: str = "OT-2",
    api_level: Union[str, float] = "2.23"
) -> str:
    """Converts natural language instructions into an OpenTron protocol using DeepSeek LLM."""
    try:
        # Create a prompt for the DeepSeek model to extract structured protocol information
        prompt = f"""
        You are an expert in creating OpenTron protocols. Convert the following natural language instructions into a structured JSON representation of an OpenTron protocol.
        
        Here's information about available labware types:
        - corning_96_wellplate_360ul_flat: Standard 96-well plate
        - opentrons_96_tiprack_300ul: Tip rack for 300µl pipettes
        - opentrons_96_tiprack_20ul: Tip rack for 20µl pipettes
        - opentrons_96_tiprack_1000ul: Tip rack for 1000µl pipettes
        - nest_12_reservoir_15ml: 12-well reservoir
        
        Here's information about available pipette types:
        - p300_single: Single-channel 300µl pipette (for volumes up to 300µl)
        - p300_multi: Multi-channel 300µl pipette (for volumes up to 300µl)
        - p20_single: Single-channel 20µl pipette (for volumes up to 20µl)
        - p20_multi: Multi-channel 20µl pipette (for volumes up to 20µl)
        - p1000_single: Single-channel 1000µl pipette (for volumes up to 1000µl)
        - p1000_multi: Multi-channel 1000µl pipette (for volumes up to 1000µl)
        
        IMPORTANT GUIDELINES:
        1. DEFAULT LABWARE AND EQUIPMENT (if user didn't specify):
           - Default plate: corning_96_wellplate_360ul_flat in position 1 (name: "plate")
           - Default tip rack: opentrons_96_tiprack_300ul in position 2 (name: "tiprack")
           - Default reservoir: corning_96_wellplate_360ul_flat in position 3 (name: "reservoir")
           - Default pipette: p300_single on right mount (name: "p300")
           - ALWAYS include these defaults in EVERY protocol unless user explicitly specifies different labware and position
           - If user mentions simple transfers without specifying labware, use plate and reservoir as source/destination
        
        2. SELECT THE APPROPRIATE PIPETTE based on the volume mentioned in the instructions:
           - Use p20_single/multi for very small volumes (1-20µl)
           - Use p300_single/multi for medium volumes (20-300µl)
           - Use p1000_single/multi for large volumes (300-1000µl)
           - If the user specifically mentions p1000, ALWAYS use p1000_single or p1000_multi
        
        3. HANDLE LARGE VOLUME TRANSFERS:
           - If a transfer volume exceeds the pipette's maximum capacity, create a loop to handle it in multiple steps
           - For example, if transferring 5000µl with a p1000: create a loop that performs 5 iterations of 1000µl transfers
           - If using p300 for large volumes, create a loop with more iterations
        
        4. WHEN READING A CSV FILE:
           - Use the MCP tool 'read_csv_to_dataframe' to read the CSV file and assign the result to a variable called 'data'.
           - 'data' will be a list of dictionaries, one per row.
           - To loop over the rows, ALWAYS use: for row in data:
           - To access a value from a column, ALWAYS use row['column_name'] (for example, row['volume']).
           - NEVER use df.loc[i, ...] or any pandas DataFrame indexing in generated code or JSON. Only use row['column_name'] for dynamic values from CSV rows.
           - When generating JSON for commands inside the loop, use parameter values like "row['volume']" (as a string) for dynamic values from the CSV.

        5. HEIGHT CONTROL FOR ASPIRATE/DISPENSE (top/bottom with offsets):
            - For any command that targets a well (aspirate/dispense and transfer source/destination), you can specify where in Z to go using:
              - For aspirate: 'aspirate_ref' ("top" or "bottom") and 'aspirate_offset' (float mm; positive above reference, negative below)
              - For dispense: 'dispense_ref' ("top" or "bottom") and 'dispense_offset' (float mm; positive above reference, negative below)
              - For transfer: use 'source_ref'/'source_offset' and 'dest_ref'/'dest_offset' respectively
            - Offsets may be numbers (e.g., 3, -2) or dynamic strings like "row['z']" when looping over CSV rows.
            - Examples:
              - Aspirate 50µl at 3mm above bottom of plate A1: {{"command_type": "aspirate", "params": {{"pipette": "p300", "volume": 50, "labware": "plate", "well": "A1", "aspirate_ref": "bottom", "aspirate_offset": 3}}}}
              - Dispense 50µl 2mm below the top of plate B1: {{"command_type": "dispense", "params": {{"pipette": "p300", "volume": 50, "labware": "plate", "well": "B1", "dispense_ref": "top", "dispense_offset": -2}}}}
              - Transfer 100µl from reservoir A1 bottom(1) to plate C3 top(-2): {{"command_type": "transfer", "params": {{"pipette": "p300", "volume": 100, "source_labware": "reservoir", "source_well": "A1", "source_ref": "bottom", "source_offset": 1, "dest_labware": "plate", "dest_well": "C3", "dest_ref": "top", "dest_offset": -2}}}}

        6. DELAYS / WAITS:
            - Use a 'delay' command. It supports 'seconds' and/or 'minutes'.
            - Optionally include 'pipette' to perform pipette.delay(...) instead of protocol.delay(...)
            - Optionally include 'message' (or 'text'/'comment') to add protocol.comment(...) before the delay.
            - Examples:
              - {{"command_type": "delay", "params": {{"seconds": 10, "message": "Pausing for 10 seconds..."}}}}
              - {{"command_type": "delay", "params": {{"minutes": 2, "pipette": "p300", "message": "Pausing 2 minutes on p300"}}}}

        7. MOVE TO LOCATION:
            - Use a 'move_to' command to move the pipette to a specific location without aspirating or dispensing.
            - Required params: pipette, labware, well
            - Optional height params: ref ("top"|"bottom"), offset (float or dynamic string)
            - Examples:
              - {{"command_type": "move_to", "params": {{"pipette": "p300", "labware": "plate", "well": "A1"}}}}
              - {{"command_type": "move_to", "params": {{"pipette": "p300", "labware": "plate", "well": "B1", "ref": "bottom", "offset": 5}}}}
        
         SPECIAL INSTRUCTION FOR TABLE-BASED TRANSFERS:
        - If the user provides a list of transfer instructions (e.g., 'transfer 100ul from A1 to E4'), you MUST:
            1. Parse each instruction into a row of a table (or DataFrame) with columns:
                - source: the well to aspirate from
                - destination: the well to dispense to
                - volume: the volume to transfer (in ul)
            2. In the JSON, output a command:
                {{
                  "command_type": "table_transfer",
                  "params": {{
                    "data": [ ... ],  // list of dicts
                    "pipette": "p300",
                    "labware": "plate"
                  }}
                }}
            3. In the generated Python code, use:
                import pandas as pd
                data = pd.DataFrame([...])
                for i in range(len(data)):
                    pipettes['p300'].pick_up_tip()
                    pipettes['p300'].aspirate(data.loc[i, 'volume'], labware['plate'][data.loc[i, 'source']])
                    pipettes['p300'].dispense(data.loc[i, 'volume'], labware['plate'][data.loc[i, 'destination']])
                    pipettes['p300'].drop_tip()
        
        - If the user provides a CSV file, you MUST:
            1. In the JSON, output a command:
                {{
                  "command_type": "table_transfer",
                  "params": {{
                    "file_path": "path/to/file.csv",
                    "pipette": "p300",
                    "labware": "plate"
                  }}
                }}
            2. In the generated Python code, use:
                import pandas as pd
                data = pd.read_csv('path/to/file.csv')
                for i in range(len(data)):
                    pipettes['p300'].pick_up_tip()
                    pipettes['p300'].aspirate(data.loc[i, 'volume'], labware['plate'][data.loc[i, 'source']])
                    pipettes['p300'].dispense(data.loc[i, 'volume'], labware['plate'][data.loc[i, 'destination']])
                    pipettes['p300'].drop_tip()
        
        # Example JSON for table-driven transfer (natural language):
        # {{
        #   "command_type": "table_transfer",
        #   "params": {{
        #     "data": [
        #       {{"source": "A4", "destination": "F5", "volume": 10}},
        #       {{"source": "A6", "destination": "G5", "volume": 100}},
        #       {{"source": "F5", "destination": "D9", "volume": 150}}
        #     ],
        #     "pipette": "p300",
        #     "labware": "plate"
        #   }}
        # }}
        # Example JSON for CSV-driven transfer:
        # {{
        #   "command_type": "table_transfer",
        #   "params": {{
        #     "file_path": "data/my_transfers.csv",
        #     "pipette": "p300",
        #     "labware": "plate"
        #   }}
        # }}
        
        OpenTron commands include:
        - load_labware: Load a labware container onto the deck
            Required params: name, labware_type, location
            Example: {{"command_type": "load_labware", "params": {{"name": "plate", "labware_type": "corning_96_wellplate_360ul_flat", "location": "1"}}}}
            
        - load_instrument: Load a pipette onto the robot
            Required params: name, instrument_type, mount
            Optional params: tip_racks (list of labware names)
            Example: {{"command_type": "load_instrument", "params": {{"name": "p300", "instrument_type": "p300_single", "mount": "right", "tip_racks": ["tiprack"]}}}}

        - read_csv: Read a CSV file and return the data as a list of dictionaries.
            Required params: file_path
            Example: {{"command_type": "read_csv", "params": {{"file_path": "data.csv"}}}}            

        -  read_csv_to_list_of_dataframes: Read a CSV file and return a list of DataFrames, each containing a single row from the CSV. Returns as a list of dicts for serialization.
            Required params: file_path
            Example: {{"command_type": "csv_to_list_of_dataframes", "params": {{"file_path": "data.csv"}}}}
            
        - pick_up_tip: Pick up a tip with a pipette
            Required params: pipette
            Optional params: labware, well
            Example: {{"command_type": "pick_up_tip", "params": {{"pipette": "p300", "labware": "tiprack", "well": "A1"}}}}
            
        - aspirate: Draw liquid into the pipette
            Required params: pipette, volume
            Recommended params: labware, well (if labware and well are not provided, aspirate from the current position)
            Optional height params: aspirate_ref ("top"|"bottom"), aspirate_offset (float or dynamic string)
            Example: {{"command_type": "aspirate", "params": {{"pipette": "p300", "volume": 100, "labware": "plate", "well": "A1", "aspirate_ref": "bottom", "aspirate_offset": 3}}}}
            
        - dispense: Dispense liquid from the pipette
            Required params: pipette, volume
            Recommended params: labware, well (if labware and well are not provided, dispense at the current position)
            Optional height params: dispense_ref ("top"|"bottom"), dispense_offset (float or dynamic string)
            Example: {{"command_type": "dispense", "params": {{"pipette": "p300", "volume": 100, "labware": "plate", "well": "B1", "dispense_ref": "top", "dispense_offset": -2}}}}
        
        - loop_over_csv: Loop over a set of commands
            Required params: commands, csv_file
            Example: {{"command_type": "loop_over_csv", "params": {{"commands": [{{"command_type": "aspirate", "params": {{"pipette": "p300", "volume": 100, "labware": "plate", "well": "A1"}}}}], "csv_file": "data.csv"}}}}
        
        - drop_tip: Discard the current tip
            Required params: pipette
            Optional params: labware, well
            Example: {{"command_type": "drop_tip", "params": {{"pipette": "p300"}}}}
            
        - comment: Add a comment in the protocol
            Required params: text
            Example: {{"command_type": "comment", "params": {{"text": "This is a comment"}}}}
            
        - delay: Wait for specified time
            Allowed params: seconds, minutes (either or both), optional pipette, optional message/text/comment
            Examples: {{"command_type": "delay", "params": {{"seconds": 5}}}} or {{"command_type": "delay", "params": {{"minutes": 2, "pipette": "p300", "message": "rest"}}}}
            
        - move_to: Move pipette to a specific location without aspirating or dispensing
            Required params: pipette, labware, well
            Optional height params: ref ("top"|"bottom"), offset (float or dynamic string)
            Example: {{"command_type": "move_to", "params": {{"pipette": "p300", "labware": "plate", "well": "A1", "ref": "bottom", "offset": 5}}}}
            
        - transfer: Transfer liquid from one well to another (handles large volumes automatically)
            Required params: pipette, volume, source_labware, source_well, dest_labware, dest_well
            Optional height params: source_ref/dest_ref ("top"|"bottom"), source_offset/dest_offset (float or dynamic string)
            Example: {{"command_type": "transfer", "params": {{"pipette": "p1000", "volume": 5000, "source_labware": "reservoir", "source_well": "A1", "dest_labware": "plate", "dest_well": "B1", "dest_ref": "bottom", "dest_offset": 1}}}}
        
        IMPORTANT: Make sure all required parameters are included for each command. For aspirate and dispense commands,
        the pipette and volume parameters are REQUIRED, while labware and well parameters are RECOMMENDED when you want to 
        specify a location. If labware and well are not provided, the operation will occur at the current position.
        
        Instructions to convert:
        {instructions}
        
        Return your answer as a valid JSON object with the following structure:
        {{
            "protocol_name": "{protocol_name}",
            "author": "{author}",
            "description": "Protocol description",
            "robot_type": "{robot_type}",
            "api_level": "{api_level}",
            "commands": [
                {{
                    "command_type": "load_labware",
                    "params": {{
                        "name": "plate",
                        "labware_type": "corning_96_wellplate_360ul_flat",
                        "location": "1"
                    }}
                }},
                {{
                    "command_type": "load_labware",
                    "params": {{
                        "name": "tiprack",
                        "labware_type": "opentrons_96_tiprack_300ul",
                        "location": "2"
                    }}
                }},
                {{
                    "command_type": "load_labware",
                    "params": {{
                        "name": "reservoir",
                        "labware_type": "nest_12_reservoir_15ml",
                        "location": "3"
                    }}
                }},
                {{
                    "command_type": "load_instrument",
                    "params": {{
                        "name": "p300",
                        "instrument_type": "p300_single",
                        "mount": "right",
                        "tip_racks": ["tiprack"]
                    }}
                }},
                ... more commands with all required parameters
            ]
        }}
        
        Only return the JSON structure, no additional explanation.
        """
        
        # Get response from DeepSeek model
        response = await model.ainvoke(prompt)
        
        # Extract the JSON from the response
        json_content = response.content
        
        # Parse thinking text from response
        json_content = parse_thinking_from_response(json_content)
        
        # Clean up the JSON content if needed (remove markdown code blocks if present)
        if "```json" in json_content:
            json_content = json_content.split("```json", 1)[1]
        if "```" in json_content:
            json_content = json_content.rsplit("```", 1)[0]
        
        json_content = json_content.strip()
        
        # Parse the JSON into a Python dictionary
        try:
            protocol_dict = json.loads(json_content)
        except json.JSONDecodeError as e:
            return f"Error parsing JSON response: {str(e)}\nResponse: {json_content[:500]}..."
        
        # Validate commands
        commands = protocol_dict.get("commands", [])
        if not commands:
            return "Error: No commands generated in protocol. Please check your instructions and try again."
        
        # Check for required labware for each pipette command
        labware_names = set()
        pipette_names = set()
        for cmd in commands:
            if cmd["command_type"] == "load_labware" and "name" in cmd["params"]:
                labware_names.add(cmd["params"]["name"])
            elif cmd["command_type"] == "load_instrument" and "name" in cmd["params"]:
                pipette_names.add(cmd["params"]["name"])
        
        # Validate that referenced labware and pipettes exist
        error_messages = []
        for i, cmd in enumerate(commands):
            # Check CSV reading commands
            if cmd["command_type"] == "read_csv":
                if "file_path" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} (read_csv): Missing required 'file_path' parameter")
            
            elif cmd["command_type"] == "read_csv_to_list_of_dataframes":
                if "file_path" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} (read_csv_to_list_of_dataframes): Missing required 'file_path' parameter")
            
            # Check aspirate and dispense commands for required labware and well parameters
            elif cmd["command_type"] == "aspirate" or cmd["command_type"] == "dispense":
                # Check for missing required parameters
                if "pipette" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} ({cmd['command_type']}): Missing required 'pipette' parameter")
                
                if "volume" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} ({cmd['command_type']}): Missing required 'volume' parameter")
                
                # Check for missing or invalid labware and well parameters
                if "labware" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} ({cmd['command_type']}): Missing required 'labware' parameter")
                elif cmd["params"]["labware"] not in labware_names:
                    error_messages.append(f"Command #{i+1} ({cmd['command_type']}): References non-existent labware '{cmd['params']['labware']}'")
                
                if "well" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} ({cmd['command_type']}): Missing required 'well' parameter")
                
                # Check if the pipette exists
                if "pipette" in cmd["params"] and cmd["params"]["pipette"] not in pipette_names:
                    error_messages.append(f"Command #{i+1} ({cmd['command_type']}): References non-existent pipette '{cmd['params']['pipette']}'")
            
            # Also check transfer commands for all required parameters
            elif cmd["command_type"] == "transfer":
                required_params = ["pipette", "volume", "source_labware", "source_well", "dest_labware", "dest_well"]
                for param in required_params:
                    if param not in cmd["params"]:
                        error_messages.append(f"Command #{i+1} (transfer): Missing required '{param}' parameter")
                
                # Validate labware references
                if "source_labware" in cmd["params"] and cmd["params"]["source_labware"] not in labware_names:
                    error_messages.append(f"Command #{i+1} (transfer): References non-existent source labware '{cmd['params']['source_labware']}'")
                
                if "dest_labware" in cmd["params"] and cmd["params"]["dest_labware"] not in labware_names:
                    error_messages.append(f"Command #{i+1} (transfer): References non-existent destination labware '{cmd['params']['dest_labware']}'")
                
                if "pipette" in cmd["params"] and cmd["params"]["pipette"] not in pipette_names:
                    error_messages.append(f"Command #{i+1} (transfer): References non-existent pipette '{cmd['params']['pipette']}'")
                
            elif cmd["command_type"] == "loop_over_csv":
                if "commands" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} (loop_over_csv): Missing required 'commands' parameter")
                if "csv_file" not in cmd["params"]:
                    error_messages.append(f"Command #{i+1} (loop_over_csv): Missing required 'csv_file' parameter")
                    
        # If we have any error messages, return them
        if error_messages:
            return "Error validating protocol:\n" + "\n".join(error_messages)
        
        # Now create a Protocol object using the same structure that create_protocol uses
        # Apply the provided user parameters instead of default values
        protocol = Protocol(
            protocol_name=protocol_dict.get("protocol_name", protocol_name),
            author=protocol_dict.get("author", author),
            description=protocol_dict.get("description", ""),
            robot_type=protocol_dict.get("robot_type", robot_type),
            api_level=str(protocol_dict.get("api_level", api_level)),  # Ensure string conversion
            commands=[ProtocolCommand(**cmd) for cmd in protocol_dict.get("commands", [])]
        )
        
        # Generate Python code using the same method as create_protocol
        python_code = protocol.to_python_code()
        
        return python_code
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"Error generating protocol: {str(e)}\n\nDetails: {error_details}"

def preprocess_protocol_code(code: str) -> str:
    """Preprocess and fix common issues in LLM-generated OpenTron protocol code."""
    import re
    
    # Remove markdown code blocks
    if "```python" in code:
        code = re.sub(r"```python\s*", "", code)
    if "```" in code:
        code = re.sub(r"```\s*", "", code)
    
    # Ensure required import exists
    if "from opentrons import protocol_api" not in code:
        # Add import at the beginning after any existing imports
        lines = code.split('\n')
        import_line = "from opentrons import protocol_api"
        
        # Find where to insert the import
        insert_pos = 0
        for i, line in enumerate(lines):
            if line.strip().startswith('import ') or line.strip().startswith('from '):
                insert_pos = i + 1
            elif line.strip() and not line.strip().startswith('#'):
                break
        
        lines.insert(insert_pos, import_line)
        code = '\n'.join(lines)
    
    # Fix common indentation issues in run function
    lines = code.split('\n')
    in_run_function = False
    corrected_lines = []
    
    for line in lines:
        if line.strip().startswith('def run('):
            in_run_function = True
            corrected_lines.append(line)
        elif in_run_function and line.strip() and not line.startswith('    ') and not line.startswith('\t'):
            # If we're in run function and line is not indented, we've left the function
            in_run_function = False
            corrected_lines.append(line)
        elif in_run_function and line.strip() and not line.startswith('    '):
            # Fix indentation inside run function
            corrected_lines.append('    ' + line.lstrip())
        else:
            corrected_lines.append(line)
    
    code = '\n'.join(corrected_lines)
    
    # Fix pandas DataFrame access patterns that LLMs sometimes generate
    code = re.sub(r"df\.loc\[i,\s*['\"]([^'\"]+)['\"]\]", r"row['\1']", code)
    code = re.sub(r"data\.loc\[i,\s*['\"]([^'\"]+)['\"]\]", r"row['\1']", code)
    
    return code

@mcp.tool(
    name="run_protocol_on_opentrons",
    description="Uploads and runs a generated OpenTrons protocol on a specified Opentrons robot via its HTTP API."
)
async def run_protocol_on_opentrons(
    protocol_code: str,
    robot_ip: str = "192.168.50.64",
    protocol_filename: str = "MyOpentronProtocol.py",
    wait_for_completion: bool = True,
    max_wait_time: int = 300
) -> str:
    """
    Uploads and runs a generated OpenTrons protocol on a specified Opentrons robot.
    Args:
        protocol_code (str): The Python code for the protocol.
        robot_ip (str): The IP address of the Opentrons robot.
        protocol_filename (str): The filename to use for the protocol (default: MyOpentronProtocol.py).
    Returns:
        str: Detailed execution status and information or error message.
    """
    import datetime
    import traceback
    
    api_base_url = f"http://{robot_ip}:31950"
    headers = {"opentrons-version": "*"}
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        # 1. Preprocess the protocol code to fix common LLM-generated issues
        processed_code = preprocess_protocol_code(protocol_code)
        
        # 2. Save protocol to file with UTF-8 encoding
        with open(protocol_filename, "w", encoding="utf-8") as f:
            f.write(processed_code)
        
        # 3. Upload protocol using the saved file
        with open(protocol_filename, "rb") as file_obj:
            files = {
                'files': (protocol_filename, file_obj, 'text/x-python')
            }
            protocol_url = f"{api_base_url}/protocols"
            upload_response = requests.post(protocol_url, files=files, headers=headers)
        
        if upload_response.status_code not in (201, 200):
            return f"ERROR: Failed to upload protocol. Status code: {upload_response.status_code}\nResponse: {upload_response.text}"
        
        protocol_id = upload_response.json().get("data", {}).get("id")
        if not protocol_id:
            return f"ERROR: Protocol uploaded but no protocol ID returned.\nResponse: {upload_response.text}"
        
        # 4. Create a run with correct JSON format
        runs_url = f"{api_base_url}/runs"
        run_payload = {"data": {"protocolId": protocol_id}}
        run_response = requests.post(runs_url, json=run_payload, headers=headers)
        
        if run_response.status_code not in (201, 200):
            return f"ERROR: Failed to create run. Status code: {run_response.status_code}\nResponse: {run_response.text}"
        
        run_id = run_response.json().get("data", {}).get("id")
        if not run_id:
            return f"ERROR: Run created but no run ID returned.\nResponse: {run_response.text}"
        
        # 5. Start the run with correct JSON format
        actions_url = f"{api_base_url}/runs/{run_id}/actions"
        action_payload = {"data": {"actionType": "play"}}
        action_response = requests.post(actions_url, json=action_payload, headers=headers)
        
        if action_response.status_code not in (201, 200):
            return f"ERROR: Failed to start run. Status code: {action_response.status_code}\nResponse: {action_response.text}"
        
        # 6. Monitor the run status until completion
        status_url = f"{api_base_url}/runs/{run_id}"
        max_wait_time = 300  # Maximum wait time in seconds (5 minutes)
        poll_interval = 3    # Check status every 3 seconds
        elapsed_time = 0
        
        print(f"Protocol started successfully. Monitoring execution status...")
        
        while elapsed_time < max_wait_time:
            try:
                status_response = requests.get(status_url, headers=headers)
                if status_response.status_code == 200:
                    run_data = status_response.json().get("data", {})
                    current_status = run_data.get("status", "unknown")
                    
                    print(f"Current status: {current_status} (elapsed: {elapsed_time}s)")
                    
                    # Check if run has completed
                    if current_status == "succeeded":
                        return f"SUCCESS: Protocol completed successfully!\nTimestamp: {timestamp}\nRun ID: {run_id}\nProtocol ID: {protocol_id}\nExecution Time: {elapsed_time} seconds"
                    
                    elif current_status == "failed":
                        # Get error details if available
                        errors = run_data.get("errors", [])
                        error_details = ""
                        if errors:
                            error_details = f"\nError Details: {'; '.join([str(err) for err in errors])}"
                        return f"FAILED: Protocol execution failed!\nTimestamp: {timestamp}\nRun ID: {run_id}\nProtocol ID: {protocol_id}\nExecution Time: {elapsed_time} seconds{error_details}"
                    
                    elif current_status == "stopped":
                        return f"STOPPED: Protocol execution was stopped!\nTimestamp: {timestamp}\nRun ID: {run_id}\nProtocol ID: {protocol_id}\nExecution Time: {elapsed_time} seconds"
                    
                    elif current_status in ["idle", "running"]:
                        # Still executing, continue monitoring
                        pass
                    
                    else:
                        print(f"Unknown status: {current_status}")
                
                else:
                    print(f"Error checking status: {status_response.status_code}")
                
            except Exception as status_error:
                print(f"Error while checking status: {status_error}")
            
            # Wait before next check
            time.sleep(poll_interval)
            elapsed_time += poll_interval
        
        # Timeout reached
        return f"TIMEOUT: Protocol execution monitoring timed out after {max_wait_time} seconds.\nTimestamp: {timestamp}\nRun ID: {run_id}\nProtocol ID: {protocol_id}\nLast known status: Check the robot interface for current status."
        
    except Exception as e:
        return f"EXCEPTION: Error during execution: {str(e)}\nDetails: {traceback.format_exc()}"
    finally:
        # Clean up the saved file
        try:
            os.remove(protocol_filename)
        except Exception:
            pass

@mcp.tool(
    name="get_opentron_resources",
    description="Returns available labware or pipette types for OpenTron"
)
async def get_opentron_resources(resource_type: str = "labware") -> str:
    """Returns available labware or pipette types for OpenTron.
    
    Args:
        resource_type: Type of resource to return. Can be 'labware' or 'pipettes'.
    """
    if resource_type.lower() == "labware":
        labware_types = [
            "corning_96_wellplate_360ul_flat",
            "corning_384_wellplate_112ul_flat",
            "opentrons_96_tiprack_10ul",
            "opentrons_96_tiprack_20ul",
            "opentrons_96_tiprack_300ul",
            "opentrons_96_tiprack_1000ul",
            "nest_12_reservoir_15ml",
            "nest_96_wellplate_100ul_pcr_full_skirt",
            "nest_96_wellplate_200ul_flat"
        ]
        return "\n".join(labware_types)
    elif resource_type.lower() == "pipettes":
        pipette_types = [
            "p10_single",
            "p10_multi",
            "p20_single",
            "p20_multi",
            "p50_single",
            "p50_multi",
            "p300_single",
            "p300_multi",
            "p1000_single",
            "p1000_multi"
        ]
        return "\n".join(pipette_types)
    else:
        return f"Unknown resource type: {resource_type}. Please use 'labware' or 'pipettes'."


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=PORT)
    