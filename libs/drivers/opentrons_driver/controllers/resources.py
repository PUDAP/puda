"""Known OT-2 labware, pipette catalogues, and custom labware management.

Standard labware load-names are listed in :data:`LABWARE_TYPES`.  Custom
labware definitions live as individual JSON files in the
``opentrons_driver/labware/`` directory and are auto-discovered at import
time — their load-names are appended to :data:`LABWARE_TYPES` automatically.

Example::

    from opentrons_driver.core.http_client import OT2HttpClient
    from opentrons_driver.controllers.resources import (
        upload_custom_labware,
        BUILTIN_LABWARE,
        get_labware_types,
    )

    client = OT2HttpClient("192.168.50.64")

    # Upload a built-in definition by load_name
    result = upload_custom_labware(client, BUILTIN_LABWARE["mass_balance_vial_30000"])
    print(result["load_name"])

    # Upload from an arbitrary JSON file
    result = upload_custom_labware(client, "/path/to/my_labware.json")

    print(get_labware_types())   # includes all custom labware from labware/
    print(get_pipette_types())
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Union

from opentrons_driver.core.http_client import OT2HttpClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auto-discover custom labware definitions from the labware/ directory
# ---------------------------------------------------------------------------

_LABWARE_DIR = Path(__file__).parent.parent / "labware"


def _load_builtin_labware() -> dict[str, dict]:
    definitions: dict[str, dict] = {}
    for json_file in sorted(_LABWARE_DIR.glob("*.json")):
        try:
            with open(json_file, encoding="utf-8") as f:
                definition = json.load(f)
            load_name = definition.get("parameters", {}).get("loadName", "")
            if not load_name:
                logger.warning(
                    "Skipping labware file '%s' — missing 'parameters.loadName'.",
                    json_file.name,
                )
                continue
            definitions[load_name] = definition
        except Exception as exc:
            logger.warning("Failed to load labware file '%s': %s", json_file.name, exc)
    return definitions


BUILTIN_LABWARE: dict[str, dict] = _load_builtin_labware()

# Convenience aliases resolved at import time (None if JSON file is removed)
MASS_BALANCE_VIAL_30ML: dict | None = BUILTIN_LABWARE.get("mass_balance_vial_30000")
MASS_BALANCE_VIAL_50ML: dict | None = BUILTIN_LABWARE.get("mass_balance_vial_50000")

# ---------------------------------------------------------------------------
# Catalogues
# ---------------------------------------------------------------------------

_STANDARD_LABWARE_TYPES: list[str] = [
    # Standard Corning plates
    "corning_96_wellplate_360ul_flat",
    "corning_384_wellplate_112ul_flat",
    # Opentrons tip racks
    "opentrons_96_tiprack_10ul",
    "opentrons_96_tiprack_20ul",
    "opentrons_96_tiprack_300ul",
    "opentrons_96_tiprack_1000ul",
    # NEST reservoirs and plates
    "nest_12_reservoir_15ml",
    "nest_96_wellplate_100ul_pcr_full_skirt",
    "nest_96_wellplate_200ul_flat",
]

# Merge standard list with any custom labware discovered from the JSON folder
LABWARE_TYPES: list[str] = _STANDARD_LABWARE_TYPES + [
    name for name in BUILTIN_LABWARE if name not in _STANDARD_LABWARE_TYPES
]

PIPETTE_TYPES: list[str] = [
    "p10_single_gen2",
    "p10_multi_gen2",
    "p20_single_gen2",
    "p20_multi_gen2",
    "p300_single_gen2",
    "p300_multi_gen2",
    "p1000_single_gen2",
    "p1000_multi_gen2",
]

# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def get_labware_types() -> list[str]:
    """Return all known labware load-names (standard + custom from labware/)."""
    return list(LABWARE_TYPES)


def get_pipette_types() -> list[str]:
    """Return all known pipette instrument names."""
    return list(PIPETTE_TYPES)


# ---------------------------------------------------------------------------
# Upload function
# ---------------------------------------------------------------------------


def upload_custom_labware(
    client: OT2HttpClient,
    labware: Union[dict, str, Path],
) -> dict:
    """Upload a custom labware definition to the robot.

    Args:
        client: Connected :class:`~opentrons_driver.core.http_client.OT2HttpClient`.
        labware: Either a labware definition ``dict``, or a path (``str`` or
            :class:`~pathlib.Path`) to a JSON file containing the definition.

    Returns:
        A dict with keys: ``load_name``, ``namespace``, ``version``,
        ``display_name``, ``already_exists`` (bool).

    Raises:
        FileNotFoundError: If a path is given but the file does not exist.
        ValueError: If the definition is missing ``parameters.loadName``.
        RuntimeError: If the robot returns an unexpected HTTP error.
    """
    if isinstance(labware, (str, Path)):
        path = Path(labware)
        if not path.exists():
            raise FileNotFoundError(f"Labware file not found: {path}")
        with open(path, encoding="utf-8") as f:
            labware_data: dict = json.load(f)
    else:
        labware_data = labware

    namespace = labware_data.get("namespace", "custom")
    load_name = labware_data.get("parameters", {}).get("loadName", "")
    version = labware_data.get("version", 1)
    display_name = labware_data.get("metadata", {}).get("displayName", "")

    if not load_name:
        raise ValueError(
            "Invalid labware definition — missing 'loadName' in 'parameters'."
        )

    resp = client.post(
        "/labware/definitions",
        json=labware_data,
        headers={"Content-Type": "application/json", "Opentrons-Version": "3"},
        timeout=10,
    )

    already_exists = resp.status_code == 409
    success = resp.status_code in (200, 201) or already_exists

    result = {
        "load_name": load_name,
        "namespace": namespace,
        "version": version,
        "display_name": display_name,
        "already_exists": already_exists,
        "http_status": resp.status_code,
        "usage": f"protocol.load_labware('{load_name}', slot, namespace='{namespace}')",
    }

    if success:
        logger.info(
            "Custom labware '%s' uploaded (namespace=%s, already_exists=%s)",
            load_name,
            namespace,
            already_exists,
        )
    else:
        logger.error(
            "Failed to upload labware '%s' (HTTP %s): %s",
            load_name,
            resp.status_code,
            resp.text[:500],
        )
        raise RuntimeError(
            f"Failed to upload labware '{load_name}' "
            f"(HTTP {resp.status_code}): {resp.text[:500]}"
        )

    return result
