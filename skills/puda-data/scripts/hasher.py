"""
puda-data Phase 2: Data Hasher

Hash and validate experimental data for data provenance.
Uses SHA-256 to ensure data integrity.
"""

import hashlib
import json
import pandas as pd
from typing import Dict, Any, Optional

# Import extractor for data access (uses config internally)
from extractor import (
    extract_measurement_data,
    get_run_info,
    get_protocol,
    get_runs_by_type,
    _get_connection
)
from registry import SchemaRegistry


def hash_measurement(df: pd.DataFrame) -> str:
    """
    Compute SHA-256 hash of measurement data.

    The hash is computed from a sorted, normalized representation
    of the data to ensure consistent results regardless of row order.

    Args:
        df: DataFrame with measurement data

    Returns:
        Hash string in format "sha256:..."
    """
    if df.empty:
        return "sha256:empty"

    # Convert to sorted JSON for consistent hashing
    # Sort by first column (potential for CV) to ensure consistency
    first_col = df.columns[0]
    df_sorted = df.sort_values(by=first_col).reset_index(drop=True)

    # Convert to sorted records
    records = df_sorted.to_dict(orient="records")
    records_sorted = sorted(records, key=lambda x: sorted(x.items()))

    data_str = json.dumps(records_sorted, sort_keys=True)
    hash_obj = hashlib.sha256(data_str.encode())

    return f"sha256:{hash_obj.hexdigest()}"


def hash_string(data: str) -> str:
    """
    Compute SHA-256 hash of a string.

    Args:
        data: String to hash

    Returns:
        Hash string in format "sha256:..."
    """
    hash_obj = hashlib.sha256(data.encode())
    return f"sha256:{hash_obj.hexdigest()}"


def hash_run(run_id: str) -> str:
    """
    Compute aggregate hash of all commands in a run.

    Args:
        run_id: The run identifier

    Returns:
        Hash string representing the entire run
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT command_name, step_number, payload FROM command_log WHERE run_id=? ORDER BY step_number",
            (run_id,)
        )
        rows = cursor.fetchall()

        # Hash each command and combine
        all_hashes = []
        for cmd_name, step, payload in rows:
            cmd_hash = hash_string(f"{step}:{cmd_name}:{payload[:100]}")  # Hash of command summary
            all_hashes.append(cmd_hash)

        # Combine all hashes
        combined = "|".join(sorted(all_hashes))
        return hash_string(combined)

    finally:
        conn.close()


def generate_fingerprint(run_id: str, command_name: str = "CV") -> Dict[str, Any]:
    """
    Generate full fingerprint with metadata and all hashes.

    Args:
        run_id: The run identifier
        command_name: Measurement command to fingerprint (default: CV)

    Returns:
        Dictionary with fingerprint information
    """
    # Get measurement data
    df = extract_measurement_data(run_id, command_name)

    # Get run info
    run_info = get_run_info(run_id)

    # Compute hashes
    measurement_hash = hash_measurement(df) if not df.empty else "sha256:no_data"
    run_hash = hash_run(run_id)

    # Compute checksum (hash of hashes)
    checksum_input = f"{measurement_hash}|{run_hash}"
    checksum = hash_string(checksum_input)

    # Build fingerprint
    fingerprint = {
        "run_id": run_id,
        "command_name": command_name,
        "measurement_hash": measurement_hash,
        "run_hash": run_hash,
        "checksum": checksum,
        "data_points": len(df),
        "protocol_id": run_info.get("protocol_id"),
        "created_at": run_info.get("created_at"),
    }

    # Add data-specific info if available
    if not df.empty:
        # Use schema to determine range column names
        device = run_info.get("commands", [{}])[0].get("device", "first") if run_info.get("commands") else "first"
        schema = SchemaRegistry.get_or_default(device, command_name)

        # Map schema columns to actual DataFrame columns
        x_col = schema.primary_x if schema.primary_x in df.columns else df.columns[0]
        y_col = schema.primary_y if schema.primary_y in df.columns else (df.columns[1] if len(df.columns) > 1 else df.columns[0])

        fingerprint["x_range"] = [float(df[x_col].min()), float(df[x_col].max())]
        fingerprint["y_range"] = [float(df[y_col].min()), float(df[y_col].max())]
        fingerprint["x_column"] = x_col
        fingerprint["y_column"] = y_col

    return fingerprint


def verify_integrity(run_id: str, expected_hash: str, command_name: str = "CV") -> bool:
    """
    Verify data integrity by comparing hashes.

    Args:
        run_id: The run identifier
        expected_hash: Expected SHA-256 hash
        command_name: Measurement command to verify

    Returns:
        True if hashes match, False otherwise
    """
    df = extract_measurement_data(run_id, command_name)
    actual_hash = hash_measurement(df)

    return actual_hash == expected_hash


def compare_runs(run_id1: str, run_id2: str, command_name: str = "CV") -> Dict[str, Any]:
    """
    Compare two runs and show how different their hashes are.

    Args:
        run_id1: First run ID
        run_id2: Second run ID
        command_name: Measurement command to compare

    Returns:
        Dictionary with comparison results
    """
    fp1 = generate_fingerprint(run_id1, command_name)
    fp2 = generate_fingerprint(run_id2, command_name)

    return {
        "run_1": run_id1,
        "run_2": run_id2,
        "hash_1": fp1["measurement_hash"],
        "hash_2": fp2["measurement_hash"],
        "hashes_equal": fp1["measurement_hash"] == fp2["measurement_hash"],
        "data_points_1": fp1["data_points"],
        "data_points_2": fp2["data_points"],
    }


def demonstrate_integrity(run_id: str = None, command_name: str = "CV") -> Dict[str, Any]:
    """
    Demonstrate how hash changes when data is modified.

    Shows original hash, modifies one value, then shows the new hash.
    They should be completely different!

    Args:
        run_id: Run ID to demonstrate with (uses latest if not provided)
        command_name: Measurement type

    Returns:
        Dictionary with demonstration results
    """
    # Get latest run if not provided
    if run_id is None:
        runs = get_runs_by_type(command_name, 1)
        if not runs:
            return {"error": f"No {command_name} runs found"}
        run_id = runs[0][0]

    # Step 1: Get original data
    df_original = extract_measurement_data(run_id, command_name)

    if df_original.empty:
        return {"error": f"No data found for run {run_id}"}

    # Step 2: Compute original hash
    original_hash = hash_measurement(df_original)

    # Step 3: Modify one value (1% change)
    df_modified = df_original.copy()
    current_col = df_modified.columns[1]  # current for CV
    original_value = df_modified.loc[0, current_col]
    modified_value = original_value * 1.01  # 1% increase
    df_modified.loc[0, current_col] = modified_value

    # Step 4: Compute modified hash
    modified_hash = hash_measurement(df_modified)

    return {
        "run_id": run_id,
        "original_hash": original_hash,
        "modified_hash": modified_hash,
        "hashes_different": original_hash != modified_hash,
        "modification": {
            "column": current_col,
            "original_value": float(original_value),
            "modified_value": float(modified_value),
            "change_percent": 1.0
        }
    }


# Quick test
if __name__ == "__main__":
    print("=== Testing Hasher ===\n")

    # Get latest CV run
    runs = get_runs_by_type("CV", 1)
    if runs:
        run_id = runs[0][0]

        # Generate fingerprint
        print("1. Fingerprint:")
        fp = generate_fingerprint(run_id)
        for k, v in fp.items():
            print(f"   {k}: {v}")

        # Demonstrate integrity
        print("\n2. Integrity Demo:")
        demo = demonstrate_integrity(run_id)
        print(f"   Original hash: {demo['original_hash'][:50]}...")
        print(f"   Modified hash: {demo['modified_hash'][:50]}...")
        print(f"   Hashes different: {demo['hashes_different']}")

        # Verify integrity
        print("\n3. Verify:")
        is_valid = verify_integrity(run_id, fp['measurement_hash'])
        print(f"   Integrity check: {is_valid}")
