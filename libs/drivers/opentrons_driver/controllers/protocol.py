"""Opentrons protocol builder and uploader.

Provides the :class:`Protocol` and :class:`ProtocolCommand` Pydantic models
for constructing OT-2 protocols programmatically, plus helpers to preprocess
and upload protocol code to the robot.

Example::

    from opentrons_driver.controllers.protocol import Protocol, ProtocolCommand, upload_protocol
    from opentrons_driver.core.http_client import OT2HttpClient

    client = OT2HttpClient("192.168.50.64")

    protocol = Protocol(
        protocol_name="My Transfer",
        author="Lab",
        description="Simple transfer",
        robot_type="OT-2",
        api_level="2.23",
        commands=[
            ProtocolCommand(command_type="load_labware", params={...}),
            ...
        ],
    )
    code = protocol.to_python_code()
    protocol_id = upload_protocol(client, code, "my_transfer.py")
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from typing import Any, Optional

from pydantic import BaseModel

from opentrons_driver.core.http_client import OT2HttpClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def dict_to_py_str(d: dict, indent: int = 4) -> str:
    """Render a dict as a Python literal string with double-quoted keys/values."""
    lines = ["{"]
    for i, (k, v) in enumerate(d.items()):
        comma = "," if i < len(d) - 1 else ""
        lines.append(f'{" " * indent}"{k}": "{v}"{comma}')
    lines.append("}")
    return "\n".join(lines)


def dict_to_python_str(d: dict, indent: int = 8) -> str:
    """Serialise *d* as a Python dict literal (True/False instead of true/false)."""
    json_str = json.dumps(d, indent=indent)
    json_str = json_str.replace(": false", ": False").replace(": true", ": True")
    return json_str


def _get_first(params: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    """Return the value for the first key found in *params*."""
    for k in keys:
        if k in params:
            return params[k]
    return default


def _build_location_expr(
    labware_name: str,
    well_expr: str,
    ref: Optional[str],
    offset: Optional[Any],
) -> str:
    """Build a well-location expression for aspirate/dispense/move_to commands."""
    base = f"labware[{repr(labware_name)}][{well_expr}]"
    if ref:
        ref_lower = str(ref).lower()
        if ref_lower in ("top", "bottom"):
            if offset is None or (isinstance(offset, str) and not offset.strip()):
                return f"{base}.{ref_lower}()"
            if isinstance(offset, str) and offset.strip().startswith("row["):
                return f"{base}.{ref_lower}({offset})"
            try:
                return f"{base}.{ref_lower}({float(offset)})"
            except (ValueError, TypeError):
                return f"{base}.{ref_lower}()"
    return base


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProtocolCommand(BaseModel):
    command_type: str
    params: dict[str, Any]


class Protocol(BaseModel):
    protocol_name: str
    author: str
    description: str
    robot_type: str
    api_level: str
    commands: list[ProtocolCommand]

    # ------------------------------------------------------------------
    # Embedded custom labware definitions (referenced by load_labware)
    # ------------------------------------------------------------------

    _BALANCE_30ML: dict = {
        "ordering": [["A1"]],
        "brand": {"brand": "AMDM", "brandId": ["amdm_balance_vial_30ml"]},
        "metadata": {
            "displayName": "AMDM Mass Balance with 30mL vial",
            "displayCategory": "wellPlate",
            "displayVolumeUnits": "µL",
            "tags": [],
        },
        "dimensions": {"xDimension": 127.4, "yDimension": 85, "zDimension": 130},
        "wells": {
            "A1": {
                "depth": 56,
                "totalLiquidVolume": 30000,
                "shape": "circular",
                "diameter": 17.0,
                "x": 74,
                "y": 42.5,
                "z": 65,
            }
        },
        "groups": [{"metadata": {"wellBottomShape": "flat"}, "wells": ["A1"]}],
        "parameters": {
            "format": "irregular",
            "quirks": [],
            "isTiprack": False,
            "isMagneticModuleCompatible": False,
            "loadName": "mass_balance_vial_30000",
        },
        "namespace": "custom_beta",
        "version": 1,
        "schemaVersion": 2,
        "apiLevel": "2.23",
        "cornerOffsetFromSlot": {"x": 0, "y": 0, "z": 0},
    }

    _BALANCE_50ML: dict = {
        "ordering": [["A1"]],
        "brand": {"brand": "AMDM", "brandId": ["amdm_balance_vial_50ml"]},
        "metadata": {
            "displayName": "AMDM Mass Balance with 50mL vial",
            "displayCategory": "wellPlate",
            "displayVolumeUnits": "µL",
            "tags": [],
        },
        "dimensions": {"xDimension": 127.4, "yDimension": 85, "zDimension": 150},
        "wells": {
            "A1": {
                "depth": 56,
                "totalLiquidVolume": 50000,
                "shape": "circular",
                "diameter": 17.5,
                "x": 74,
                "y": 42.5,
                "z": 65,
            }
        },
        "groups": [{"metadata": {"wellBottomShape": "flat"}, "wells": ["A1"]}],
        "parameters": {
            "format": "irregular",
            "quirks": [],
            "isTiprack": False,
            "isMagneticModuleCompatible": False,
            "loadName": "mass_balance_vial_50000",
        },
        "namespace": "custom_beta",
        "version": 1,
        "schemaVersion": 2,
        "apiLevel": "2.23",
        "cornerOffsetFromSlot": {"x": 0, "y": 0, "z": 0},
    }

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    def to_python_code(self) -> str:  # noqa: C901 – intentionally long
        """Convert this protocol definition to valid Opentrons Python code."""
        metadata = {
            "protocolName": self.protocol_name,
            "author": self.author,
            "description": self.description,
        }
        requirements = {
            "robotType": self.robot_type,
            "apiLevel": self.api_level,
        }
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

        for i, cmd in enumerate(self.commands):
            try:
                code = self._process_command(
                    code, cmd, i, data_var, data_file
                )

                # CSV setup commands set these variables for later use
                if cmd.command_type in ("read_csv_file", "read_csv"):
                    if "file_path" in cmd.params:
                        data_var = "data"
                        data_file = cmd.params["file_path"]
                        if "csv_data" in cmd.params:
                            csv_data_str = json.dumps(cmd.params["csv_data"], indent=4)
                            data_read_code = (
                                f"    # CSV data embedded directly in the protocol\n"
                                f"    {data_var} = {csv_data_str}\n\n"
                            )
                        else:
                            data_read_code = (
                                f"    import pandas as pd\n"
                                f"    {data_var} = pd.read_csv('{data_file}').to_dict(orient='records')\n\n"
                            )

            except Exception as exc:
                code += f"    # Error processing command {i + 1} ({cmd.command_type}): {exc}\n\n"

        if data_read_code:
            lines = code.split("\n")
            insert_index = len(lines)
            for j, line in enumerate(lines):
                if "load_instrument" in line or "load_labware" in line:
                    insert_index = j + 2
            lines.insert(insert_index, data_read_code.rstrip())
            code = "\n".join(lines)

        code = re.sub(r"df\.loc\[i, *'([^']+)'\]", r"row['\1']", code)
        return code

    # ------------------------------------------------------------------
    # Per-command dispatch (kept as a private method to keep to_python_code readable)
    # ------------------------------------------------------------------

    def _process_command(  # noqa: C901
        self,
        code: str,
        cmd: ProtocolCommand,
        idx: int,
        data_var: Optional[str],
        data_file: Optional[str],
    ) -> str:
        ct = cmd.command_type

        if ct in ("read_csv_file", "read_csv"):
            return code  # handled in caller

        if ct in ("loop", "loop_over_csv"):
            return self._gen_loop(code, cmd)

        if ct == "load_labware":
            return self._gen_load_labware(code, cmd, idx)

        if ct == "load_instrument":
            return self._gen_load_instrument(code, cmd, idx)

        if ct == "pick_up_tip":
            return self._gen_pick_up_tip(code, cmd, idx)

        if ct == "aspirate":
            return self._gen_aspirate(code, cmd, idx, indent=4)

        if ct == "dispense":
            return self._gen_dispense(code, cmd, idx, indent=4)

        if ct == "blow_out":
            return self._gen_blow_out(code, cmd, idx, indent=4)

        if ct == "drop_tip":
            return self._gen_drop_tip(code, cmd, idx, indent=4)

        if ct == "home":
            code += "    # Home all robot axes\n    protocol.home()\n\n"
            return code

        if ct == "flow_rate":
            return self._gen_flow_rate(code, cmd, idx, indent=4)

        if ct == "touch_tip":
            return self._gen_touch_tip(code, cmd, idx, indent=4)

        if ct == "air_gap":
            return self._gen_air_gap(code, cmd, idx, indent=4)

        if ct == "mix":
            return self._gen_mix(code, cmd, idx, indent=4)

        if ct == "comment":
            text = cmd.params.get("text", "")
            code += f"    # {text}\n\n"
            return code

        if ct == "delay":
            return self._gen_delay(code, cmd, indent=4)

        if ct == "move_to":
            return self._gen_move_to(code, cmd, idx, indent=4)

        if ct == "transfer":
            return self._gen_transfer(code, cmd, idx)


        code += f"    # Unknown command type: {ct} at command {idx + 1}\n\n"
        return code

    # ------------------------------------------------------------------
    # Loop generator
    # ------------------------------------------------------------------

    def _gen_loop(self, code: str, cmd: ProtocolCommand) -> str:
        code += "    for row in data:\n"
        for subcmd_raw in cmd.params.get("commands", []):
            subcmd = (
                ProtocolCommand(**subcmd_raw)
                if isinstance(subcmd_raw, dict)
                else subcmd_raw
            )
            ct = subcmd.command_type
            code = self._process_subcommand(code, subcmd, ct)
        code += "\n"
        return code

    def _process_subcommand(self, code: str, cmd: ProtocolCommand, ct: str) -> str:  # noqa: C901
        """Generate code for a command nested inside a loop (8-space indent)."""
        if ct == "pick_up_tip":
            code += f"        pipettes['{cmd.params['pipette']}'].pick_up_tip()\n"
            return code

        if ct == "drop_tip":
            code += f"        pipettes['{cmd.params['pipette']}'].drop_tip()\n"
            return code

        if ct == "home":
            code += "        protocol.home()\n"
            return code

        if ct == "aspirate":
            return self._gen_aspirate(code, cmd, 0, indent=8)

        if ct == "dispense":
            return self._gen_dispense(code, cmd, 0, indent=8)

        if ct == "blow_out":
            return self._gen_blow_out(code, cmd, 0, indent=8)

        if ct == "flow_rate":
            return self._gen_flow_rate(code, cmd, 0, indent=8)

        if ct == "touch_tip":
            return self._gen_touch_tip(code, cmd, 0, indent=8)

        if ct == "air_gap":
            return self._gen_air_gap(code, cmd, 0, indent=8)

        if ct == "mix":
            return self._gen_mix(code, cmd, 0, indent=8)

        if ct == "move_to":
            return self._gen_move_to(code, cmd, 0, indent=8)

        if ct == "delay":
            return self._gen_delay(code, cmd, indent=8)

        if ct == "comment":
            text = cmd.params.get("text", "")
            code += f"        # {text}\n"
            return code

        return code

    # ------------------------------------------------------------------
    # Individual command generators
    # ------------------------------------------------------------------

    def _gen_load_labware(self, code: str, cmd: ProtocolCommand, idx: int) -> str:
        p = cmd.params
        if not all(k in p for k in ("name", "labware_type", "location")):
            code += (
                f"    # Error: Missing required parameter for load_labware at command {idx + 1}\n"
                f"    # Required: name, labware_type, location\n"
                f"    # Received: {p}\n\n"
            )
            return code

        labware_type = p["labware_type"].split("/", 1)[-1]  # strip namespace prefix

        if labware_type == "mass_balance_vial_30000":
            json_str = dict_to_python_str(self._BALANCE_30ML, indent=8)
            code += (
                f"    # Load mass balance vial (30mL) with embedded definition\n"
                f"    balance_30ml_def = {json_str}\n"
                f"    labware[{repr(p['name'])}] = protocol.load_labware_from_definition(\n"
                f"        balance_30ml_def, location={repr(p['location'])}\n"
                f"    )\n\n"
            )
        elif labware_type == "mass_balance_vial_50000":
            json_str = dict_to_python_str(self._BALANCE_50ML, indent=8)
            code += (
                f"    # Load mass balance vial (50mL) with embedded definition\n"
                f"    balance_50ml_def = {json_str}\n"
                f"    labware[{repr(p['name'])}] = protocol.load_labware_from_definition(\n"
                f"        balance_50ml_def, location={repr(p['location'])}\n"
                f"    )\n\n"
            )
        else:
            code += (
                f"    labware[{repr(p['name'])}] = protocol.load_labware(\n"
                f"        {repr(labware_type)}, location={repr(p['location'])}\n"
                f"    )\n\n"
            )
        return code

    def _gen_load_instrument(self, code: str, cmd: ProtocolCommand, idx: int) -> str:
        p = cmd.params
        if not all(k in p for k in ("name", "instrument_type", "mount")):
            code += (
                f"    # Error: Missing required parameter for load_instrument at command {idx + 1}\n"
                f"    # Required: name, instrument_type, mount\n"
                f"    # Received: {p}\n\n"
            )
            return code
        tip_racks = p.get("tip_racks", [])
        tip_racks_str = ", ".join([f"labware[{repr(rack)}]" for rack in tip_racks])
        code += (
            f"    pipettes[{repr(p['name'])}] = protocol.load_instrument(\n"
            f"        {repr(p['instrument_type'])},\n"
            f"        mount={repr(p['mount'])}"
        )
        if tip_racks:
            code += f",\n        tip_racks=[{tip_racks_str}]"
        code += "\n    )\n\n"
        return code

    def _gen_pick_up_tip(self, code: str, cmd: ProtocolCommand, idx: int) -> str:
        p = cmd.params
        if "pipette" not in p:
            code += (
                f"    # Error: Missing 'pipette' for pick_up_tip at command {idx + 1}\n\n"
            )
            return code
        if "well" in p and "labware" in p:
            code += (
                f"    pipettes['{p['pipette']}'].pick_up_tip("
                f"labware['{p['labware']}']['{p['well']}'])\n\n"
            )
        else:
            code += f"    pipettes['{p['pipette']}'].pick_up_tip()\n\n"
        return code

    def _gen_aspirate(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p or "volume" not in p:
            code += (
                f"{pad}# Error: Missing pipette/volume for aspirate at command {idx + 1}\n"
            )
            return code
        vol_str = self._vol_str(p["volume"])
        well_str = self._well_str(p.get("well", ""))
        asp_ref = _get_first(p, ["aspirate_ref", "aspirate_position", "aspirate_height_ref", "position", "ref"])
        asp_off = _get_first(p, ["aspirate_offset", "aspirate_height", "aspirate_z_offset", "offset", "z_offset"])
        rate_part = self._rate_str(p, "aspirate_rate")

        if "labware" in p and "well" in p:
            loc = _build_location_expr(p["labware"], well_str, asp_ref, asp_off)
            code += f"{pad}pipettes['{p['pipette']}'].aspirate({vol_str}, {loc}{rate_part})\n"
        else:
            code += f"{pad}pipettes['{p['pipette']}'].aspirate({vol_str}{rate_part})\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_dispense(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p or "volume" not in p:
            code += f"{pad}# Error: Missing pipette/volume for dispense at command {idx + 1}\n"
            return code
        vol_str = self._vol_str(p["volume"])
        well_str = self._well_str(p.get("well", ""))
        dsp_ref = _get_first(p, ["dispense_ref", "dispense_position", "dispense_height_ref", "position", "ref"])
        dsp_off = _get_first(p, ["dispense_offset", "dispense_height", "dispense_z_offset", "offset", "z_offset"])
        rate_part = self._rate_str(p, "dispense_rate")

        if "labware" in p and "well" in p:
            loc = _build_location_expr(p["labware"], well_str, dsp_ref, dsp_off)
            code += f"{pad}pipettes['{p['pipette']}'].dispense({vol_str}, {loc}{rate_part})\n"
        else:
            code += f"{pad}pipettes['{p['pipette']}'].dispense({vol_str}{rate_part})\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_blow_out(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p:
            code += f"{pad}# Error: Missing 'pipette' for blow_out at command {idx + 1}\n"
            return code
        well_str = self._well_str(p.get("well", ""))
        blow_ref = _get_first(p, ["blow_ref", "blow_position", "blow_height_ref", "position", "ref"])
        blow_off = _get_first(p, ["blow_offset", "blow_height", "blow_z_offset", "offset", "z_offset"])
        if "labware" in p and "well" in p:
            loc = _build_location_expr(p["labware"], well_str, blow_ref, blow_off)
            code += f"{pad}pipettes['{p['pipette']}'].blow_out({loc})\n"
        else:
            code += f"{pad}pipettes['{p['pipette']}'].blow_out()\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_drop_tip(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p:
            code += f"{pad}# Error: Missing 'pipette' for drop_tip at command {idx + 1}\n"
            return code
        if "well" in p and "labware" in p:
            code += (
                f"{pad}pipettes['{p['pipette']}'].drop_tip("
                f"labware['{p['labware']}']['{p['well']}'])\n"
            )
        else:
            code += f"{pad}pipettes['{p['pipette']}'].drop_tip()\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_flow_rate(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p:
            code += f"{pad}# Error: Missing 'pipette' for flow_rate at command {idx + 1}\n"
            return code
        asp = p.get("aspirate")
        dsp = p.get("dispense")
        blow = p.get("blow_out")
        if asp is None and dsp is None and blow is None:
            code += f"{pad}# Warning: flow_rate called with no rate parameters\n"
        else:
            if asp is not None:
                code += f"{pad}pipettes['{p['pipette']}'].flow_rate.aspirate = {asp}  # µL/s\n"
            if dsp is not None:
                code += f"{pad}pipettes['{p['pipette']}'].flow_rate.dispense = {dsp}  # µL/s\n"
            if blow is not None:
                code += f"{pad}pipettes['{p['pipette']}'].flow_rate.blow_out = {blow}  # µL/s\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_touch_tip(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p:
            code += f"{pad}# Error: Missing 'pipette' for touch_tip at command {idx + 1}\n"
            return code
        well_str = self._well_str(p.get("well", ""))
        if "labware" in p and "well" in p:
            radius = p.get("radius", 1.0)
            v_offset = p.get("v_offset", -1)
            speed = p.get("speed", 60)
            code += (
                f"{pad}pipettes['{p['pipette']}'].touch_tip("
                f"labware['{p['labware']}'][{well_str}], "
                f"radius={radius}, v_offset={v_offset}, speed={speed})\n"
            )
        else:
            code += f"{pad}pipettes['{p['pipette']}'].touch_tip()\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_air_gap(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p:
            code += f"{pad}# Error: Missing 'pipette' for air_gap at command {idx + 1}\n"
            return code
        vol_str = self._vol_str(p.get("volume", 10))
        height_str = self._vol_str(p.get("height", 5))
        code += f"{pad}pipettes['{p['pipette']}'].air_gap({vol_str}, height={height_str})\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_mix(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if "pipette" not in p:
            code += f"{pad}# Error: Missing 'pipette' for mix at command {idx + 1}\n"
            return code
        reps_param = p.get("repetitions", 3)
        reps_str = (
            reps_param
            if isinstance(reps_param, str) and reps_param.strip().startswith("row[")
            else str(int(reps_param))
        )
        vol_str = self._vol_str(p.get("volume", 100))
        well_str = self._well_str(p.get("well", ""))
        mix_ref = _get_first(p, ["mix_ref", "mix_position", "mix_height_ref", "position", "ref"])
        mix_off = _get_first(p, ["mix_offset", "mix_height", "mix_z_offset", "offset", "z_offset"])
        if "labware" in p and "well" in p:
            loc = _build_location_expr(p["labware"], well_str, mix_ref, mix_off)
            code += f"{pad}pipettes['{p['pipette']}'].mix({reps_str}, {vol_str}, {loc})\n"
        else:
            code += f"{pad}pipettes['{p['pipette']}'].mix({reps_str}, {vol_str})\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_delay(self, code: str, cmd: ProtocolCommand, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        seconds = _get_first(p, ["seconds"])
        minutes = _get_first(p, ["minutes"])
        message = _get_first(p, ["message", "text", "comment"])
        pipette = _get_first(p, ["pipette"])
        if message:
            code += f"{pad}protocol.comment({repr(str(message))})\n"
        if pipette:
            args = []
            if minutes is not None:
                args.append(f"minutes={minutes}")
            if seconds is not None:
                args.append(f"seconds={seconds}")
            arg_str = ", ".join(args) if args else "seconds=1"
            code += f"{pad}pipettes['{pipette}'].delay({arg_str})\n"
        else:
            if minutes is not None and seconds is not None:
                code += f"{pad}protocol.delay(minutes={minutes}, seconds={seconds})\n"
            elif minutes is not None:
                code += f"{pad}protocol.delay(minutes={minutes})\n"
            elif seconds is not None:
                code += f"{pad}protocol.delay(seconds={seconds})\n"
            else:
                code += f"{pad}protocol.delay(seconds=1)\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_move_to(self, code: str, cmd: ProtocolCommand, idx: int, *, indent: int) -> str:
        pad = " " * indent
        p = cmd.params
        if not all(k in p for k in ("pipette", "labware", "well")):
            code += f"{pad}# Error: Missing required parameter for move_to at command {idx + 1}\n"
            return code
        well_str = self._well_str(p.get("well", ""))
        move_ref = _get_first(p, ["move_ref", "move_position", "move_height_ref", "position", "ref"])
        move_off = _get_first(p, ["move_offset", "move_height", "move_z_offset", "offset", "z_offset"])
        if move_ref is None:
            move_ref = "top"
            if move_off is None:
                move_off = 10
        loc = _build_location_expr(p["labware"], well_str, move_ref, move_off)
        code += f"{pad}pipettes['{p['pipette']}'].move_to({loc})\n"
        if indent == 4:
            code += "\n"
        return code

    def _gen_transfer(self, code: str, cmd: ProtocolCommand, idx: int) -> str:  # noqa: C901
        p = cmd.params
        required = ("pipette", "volume", "source_labware", "source_well", "dest_labware", "dest_well")
        if not all(k in p for k in required):
            code += (
                f"    # Error: Missing required parameter for transfer at command {idx + 1}\n"
                f"    # Required: {', '.join(required)}\n\n"
            )
            return code

        pipette_name = p["pipette"]
        volume = float(p["volume"])
        pipette_max_vol = 1000 if "p1000" in pipette_name else 300 if "p300" in pipette_name else 20

        src_ref = _get_first(p, ["source_ref", "source_position", "source_height_ref"])
        src_off = _get_first(p, ["source_offset", "source_height", "source_z_offset"])
        dst_ref = _get_first(p, ["dest_ref", "dest_position", "dest_height_ref"])
        dst_off = _get_first(p, ["dest_offset", "dest_height", "dest_z_offset"])
        source_expr = _build_location_expr(p["source_labware"], f"'{p['source_well']}'", src_ref, src_off)
        dest_expr = _build_location_expr(p["dest_labware"], f"'{p['dest_well']}'", dst_ref, dst_off)

        transfer_rate = p.get("rate")
        aspirate_rate = p.get("aspirate_rate")
        dispense_rate = p.get("dispense_rate")
        use_separate = (aspirate_rate is not None or dispense_rate is not None) and transfer_rate is None

        if use_separate:
            asp_rp = f", rate={aspirate_rate}" if aspirate_rate is not None else ""
            dsp_rp = f", rate={dispense_rate}" if dispense_rate is not None else ""
            if volume <= pipette_max_vol:
                code += (
                    f"    pipettes['{pipette_name}'].pick_up_tip()\n"
                    f"    pipettes['{pipette_name}'].aspirate({volume}, {source_expr}{asp_rp})\n"
                    f"    pipettes['{pipette_name}'].dispense({volume}, {dest_expr}{dsp_rp})\n"
                    f"    pipettes['{pipette_name}'].drop_tip()\n\n"
                )
            else:
                iterations = int(volume // pipette_max_vol)
                remainder = volume % pipette_max_vol
                code += f"    pipettes['{pipette_name}'].pick_up_tip()\n"
                if iterations:
                    code += (
                        f"    for _ in range({iterations}):\n"
                        f"        pipettes['{pipette_name}'].aspirate({pipette_max_vol}, {source_expr}{asp_rp})\n"
                        f"        pipettes['{pipette_name}'].dispense({pipette_max_vol}, {dest_expr}{dsp_rp})\n"
                    )
                if remainder:
                    code += (
                        f"    pipettes['{pipette_name}'].aspirate({remainder}, {source_expr}{asp_rp})\n"
                        f"    pipettes['{pipette_name}'].dispense({remainder}, {dest_expr}{dsp_rp})\n"
                    )
                code += f"    pipettes['{pipette_name}'].drop_tip()\n\n"
        else:
            rate_param = f", rate={transfer_rate}" if transfer_rate is not None else ""
            if volume <= pipette_max_vol:
                code += f"    pipettes['{pipette_name}'].transfer({volume}, {source_expr}, {dest_expr}{rate_param})\n\n"
            else:
                iterations = int(volume // pipette_max_vol)
                remainder = volume % pipette_max_vol
                if iterations:
                    code += (
                        f"    for _ in range({iterations}):\n"
                        f"        pipettes['{pipette_name}'].transfer({pipette_max_vol}, {source_expr}, {dest_expr}, new_tip='once'{rate_param})\n"
                    )
                if remainder:
                    code += (
                        f"    pipettes['{pipette_name}'].transfer({remainder}, {source_expr}, {dest_expr}, new_tip='once'{rate_param})\n"
                    )
                code += "\n"
        return code

    # ------------------------------------------------------------------
    # Tiny helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _vol_str(val: Any) -> str:
        if isinstance(val, str) and val.strip().startswith("row["):
            return val
        return str(float(val))

    @staticmethod
    def _well_str(val: Any) -> str:
        if isinstance(val, str) and val.strip().startswith("row["):
            return val
        return f"'{val}'"

    @staticmethod
    def _rate_str(params: dict, key: str) -> str:
        if key not in params:
            return ""
        v = params[key]
        if isinstance(v, str) and v.strip().startswith("row["):
            return f", rate={v}"
        return f", rate={float(v)}"


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------


def preprocess_protocol_code(code: str) -> str:
    """Fix common issues in protocol code before uploading to the robot.

    - Strips markdown fences
    - Ensures ``from opentrons import protocol_api`` is present
    - Fixes indentation inside the ``run()`` function
    - Replaces ``df.loc[i, 'col']`` patterns with ``row['col']``
    """
    if "```python" in code:
        code = re.sub(r"```python\s*", "", code)
    if "```" in code:
        code = re.sub(r"```\s*", "", code)

    if "from opentrons import protocol_api" not in code:
        lines = code.split("\n")
        insert_pos = 0
        for j, line in enumerate(lines):
            if line.strip().startswith("import ") or line.strip().startswith("from "):
                insert_pos = j + 1
            elif line.strip() and not line.strip().startswith("#"):
                break
        lines.insert(insert_pos, "from opentrons import protocol_api")
        code = "\n".join(lines)

    lines = code.split("\n")
    in_run = False
    corrected: list[str] = []
    for line in lines:
        if line.strip().startswith("def run("):
            in_run = True
            corrected.append(line)
        elif in_run and line.strip() and not line.startswith("    ") and not line.startswith("\t"):
            in_run = False
            corrected.append(line)
        elif in_run and line.strip() and not line.startswith("    "):
            corrected.append("    " + line.lstrip())
        else:
            corrected.append(line)
    code = "\n".join(corrected)

    code = re.sub(r"df\.loc\[i,\s*['\"]([^'\"]+)['\"]\]", r"row['\1']", code)
    code = re.sub(r"data\.loc\[i,\s*['\"]([^'\"]+)['\"]\]", r"row['\1']", code)
    return code


# ---------------------------------------------------------------------------
# Upload helper
# ---------------------------------------------------------------------------


def upload_protocol(
    client: OT2HttpClient,
    code: str,
    filename: str = "protocol.py",
) -> str:
    """Preprocess *code* and upload it to the robot.

    Args:
        client: Configured :class:`~opentrons_driver.core.http_client.OT2HttpClient`.
        code: Raw Python protocol code (may contain markdown fences or
            indentation issues).
        filename: Name reported to the robot for this protocol file.

    Returns:
        The ``protocolId`` string assigned by the robot.

    Raises:
        RuntimeError: If the upload fails or the robot returns no ID.
    """
    processed = preprocess_protocol_code(code)

    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, os.path.basename(filename))
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(processed)

    try:
        with open(temp_path, "rb") as f:
            resp = client.post(
                "/protocols",
                files={"files": (os.path.basename(filename), f, "text/x-python")},
            )
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to upload protocol (HTTP {resp.status_code}): {resp.text}"
        )

    protocol_id = resp.json().get("data", {}).get("id")
    if not protocol_id:
        raise RuntimeError(
            f"Protocol uploaded but no ID returned. Response: {resp.text}"
        )

    logger.info("Protocol uploaded: id=%s filename=%s", protocol_id, filename)
    return protocol_id
