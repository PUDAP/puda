"""
puda-data Phase 3: Data Exporter

Export PUDA experimental data to various formats.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from extractor import (
    extract_measurement_data,
    get_run_info,
    get_protocol
)
from hasher import generate_fingerprint
from config import get_export_dir


def export_to_csv(
    run_id: str,
    output_dir: str = None,
    command_name: str = "CV"
) -> str:
    """
    Export measurement data to CSV file.

    Args:
        run_id: The run identifier
        output_dir: Output directory (default: exports/)
        command_name: Measurement type (CV, OCV, etc.)

    Returns:
        Path to exported file
    """
    output_dir = Path(output_dir) if output_dir else get_export_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get data
    df = extract_measurement_data(run_id, command_name)

    if df.empty:
        raise ValueError(f"No data found for run {run_id}")

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{command_name.lower()}_{run_id[:8]}_{timestamp}.csv"
    filepath = output_dir / filename

    # Export
    df.to_csv(filepath, index=False)

    print(f"Exported CSV: {filepath}")
    return str(filepath)


def export_to_json(
    run_id: str,
    output_dir: str = None,
    command_name: str = "CV"
) -> str:
    """
    Export measurement data to JSON file.

    Args:
        run_id: The run identifier
        output_dir: Output directory (default: exports/)
        command_name: Measurement type (CV, OCV, etc.)

    Returns:
        Path to exported file
    """
    output_dir = Path(output_dir) if output_dir else get_export_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get data and fingerprint
    df = extract_measurement_data(run_id, command_name)
    fp = generate_fingerprint(run_id, command_name)

    if df.empty:
        raise ValueError(f"No data found for run {run_id}")

    # Build JSON structure
    data = {
        "run_id": run_id,
        "command_name": command_name,
        "parameters": fp.get("parameters", {}),
        "data_points": len(df),
        "metadata": {
            "potential_range": fp.get("potential_range", []),
            "current_range": fp.get("current_range", []),
            "created_at": fp.get("created_at"),
            "protocol_id": fp.get("protocol_id"),
        },
        "hashes": {
            "measurement_hash": fp.get("measurement_hash"),
            "run_hash": fp.get("run_hash"),
            "checksum": fp.get("checksum"),
        },
        "data": df.to_dict(orient="records"),
    }

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{command_name.lower()}_{run_id[:8]}_{timestamp}.json"
    filepath = output_dir / filename

    # Export
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Exported JSON: {filepath}")
    return str(filepath)


def export_protocol(
    run_id: str,
    output_dir: str = None
) -> str:
    """
    Export protocol definition to JSON.

    Args:
        run_id: The run identifier
        output_dir: Output directory (default: exports/)

    Returns:
        Path to exported file
    """
    output_dir = Path(output_dir) if output_dir else get_export_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get run and protocol info
    run_info = get_run_info(run_id)
    protocol_id = run_info.get("protocol_id")

    if not protocol_id:
        raise ValueError(f"No protocol found for run {run_id}")

    protocol = get_protocol(protocol_id)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"protocol_{protocol_id[:8]}_{timestamp}.json"
    filepath = output_dir / filename

    # Export
    with open(filepath, 'w') as f:
        json.dump(protocol, f, indent=2)

    print(f"Exported Protocol: {filepath}")
    return str(filepath)


def export_full_experiment(
    run_id: str,
    output_dir: str = None,
    command_name: str = "CV"
) -> dict:
    """
    Export complete experiment: data + protocol + fingerprint.

    Args:
        run_id: The run identifier
        output_dir: Output directory (default: exports/)
        command_name: Measurement type

    Returns:
        Dictionary with paths to exported files
    """
    output_dir = Path(output_dir) if output_dir else get_export_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    try:
        results["csv"] = export_to_csv(run_id, output_dir, command_name)
    except Exception as e:
        results["csv_error"] = str(e)

    try:
        results["json"] = export_to_json(run_id, output_dir, command_name)
    except Exception as e:
        results["json_error"] = str(e)

    try:
        results["protocol"] = export_protocol(run_id, output_dir)
    except Exception as e:
        results["protocol_error"] = str(e)

    print(f"\nExported {len([k for k in results if not k.endswith('_error')])} files")
    return results


# Quick test
if __name__ == "__main__":
    print("=== Testing Exporter ===\n")

    # Get latest CV run
    from extractor import get_runs_by_type
    runs = get_runs_by_type("CV", 1)
    run_id = runs[0][0]
    print(f"Run ID: {run_id}\n")

    # Export CSV
    print("1. Export CSV:")
    csv_path = export_to_csv(run_id)

    # Export JSON
    print("\n2. Export JSON:")
    json_path = export_to_json(run_id)

    # Export Protocol
    print("\n3. Export Protocol:")
    prot_path = export_protocol(run_id)

    # Full export
    print("\n4. Full Experiment Export:")
    results = export_full_experiment(run_id)
    for k, v in results.items():
        print(f"   {k}: {v}")
