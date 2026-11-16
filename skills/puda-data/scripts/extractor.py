"""
puda-data Phase 1: Data Extractor

Extract experimental data from PUDA database.
Supports CV, OCV, CA, PEIS, GEIS and other measurement types.

Uses SchemaRegistry for column definitions and AdapterRegistry for
device-specific data extraction.
"""

import sqlite3
import json
import pandas as pd
from typing import List, Tuple, Optional, Dict, Any

from config import get_db_path
from registry import SchemaRegistry

# Lazy imports for adapters to avoid circular imports
_adapters_initialized = False


def _init_adapters():
    """Initialize device adapters."""
    global _adapters_initialized
    if not _adapters_initialized:
        from adapters import AdapterRegistry, register_all
        register_all()
        _adapters_initialized = True


def _get_connection():
    """Get database connection."""
    return sqlite3.connect(get_db_path())


def _extract_raw_payload(run_id: str, command_name: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Extract raw payload and device ID from a run.

    Returns:
        Tuple of (payload dict, device_id string)
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # Get command log with machine_id
        cursor.execute(
            "SELECT payload, machine_id FROM command_log WHERE run_id=? AND command_name=?",
            (run_id, command_name)
        )
        row = cursor.fetchone()

        if not row:
            return None, ""

        payload = json.loads(row[0])
        device_id = row[1] or "first"  # Default to "first" if not specified

        return payload, device_id
    finally:
        conn.close()


def extract_measurement_data(
    run_id: str,
    command_name: str,
    device: Optional[str] = None,
) -> pd.DataFrame:
    """
    Extract measurement data for a given run and command type.

    Args:
        run_id: The run identifier
        command_name: Command type (CV, OCV, CA, PEIS, etc.)
        device: Device identifier override (auto-detected from run if None)

    Returns:
        DataFrame with measurement data and proper column names
    """
    _init_adapters()

    from adapters import AdapterRegistry

    # Get raw payload and detect device
    payload, detected_device = _extract_raw_payload(run_id, command_name)

    if payload is None:
        return pd.DataFrame()

    # Use detected device if not explicitly specified
    if device is None:
        device = detected_device

    # Get adapter for this device
    adapter = AdapterRegistry.get_or_default(device)

    # Extract data using adapter
    df = adapter.extract_data(payload, command_name)

    return df


def get_runs_by_type(command_name: str, limit: int = 10) -> List[Tuple[str, int, str]]:
    """
    List runs containing a specific command type.

    Args:
        command_name: Command type to search for
        limit: Maximum number of results

    Returns:
        List of (run_id, step_number, created_at) tuples
    """
    conn = _get_connection()
    try:
        query = """
            SELECT run_id, step_number, created_at
            FROM command_log
            WHERE command_name=?
            ORDER BY created_at DESC
            LIMIT ?
        """
        cursor = conn.cursor()
        cursor.execute(query, (command_name, limit))
        return cursor.fetchall()
    finally:
        conn.close()


def get_latest_measurements(command_name: str, limit: int = 5) -> List[Tuple[str, pd.DataFrame]]:
    """
    Get most recent measurement data.

    Args:
        command_name: Command type (CV, OCV, etc.)
        limit: Number of recent measurements to retrieve

    Returns:
        List of (run_id, DataFrame) tuples
    """
    runs = get_runs_by_type(command_name, limit)
    results = []

    for run_id, step, created in runs:
        df = extract_measurement_data(run_id, command_name)
        if not df.empty:
            results.append((run_id, df))

    return results


def _run_metadata_columns(conn: sqlite3.Connection) -> str:
    """Select optional run fields without migrating older project databases."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(run)")}
    return ", ".join(
        f"r.{name}" if name in columns else f"NULL AS {name}"
        for name in ("steps", "notes")
    )


def get_run_info(run_id: str) -> Dict[str, Any]:
    """
    Get experiment metadata for a run.

    Args:
        run_id: The run identifier

    Returns:
        Dictionary with run information, including raw steps/notes text (or None).
        Missing runs return {}; missing legacy columns return None.
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # Get run info
        cursor.execute(
            f"SELECT r.run_id, r.protocol_id, r.created_at, {_run_metadata_columns(conn)} "
            "FROM run r WHERE r.run_id=?",
            (run_id,)
        )
        run_row = cursor.fetchone()

        if not run_row:
            return {}

        # Get all commands in this run
        cursor.execute(
            "SELECT step_number, command_name, machine_id FROM command_log WHERE run_id=? ORDER BY step_number",
            (run_id,)
        )
        commands = cursor.fetchall()

        return {
            "run_id": run_row[0],
            "protocol_id": run_row[1],
            "created_at": run_row[2],
            "steps": run_row[3],
            "notes": run_row[4],
            "commands": [{"step": c[0], "name": c[1], "device": c[2] or "first"} for c in commands],
        }
    finally:
        conn.close()


def get_protocol(protocol_id: str) -> Dict[str, Any]:
    """
    Get protocol definition.

    Args:
        protocol_id: The protocol identifier

    Returns:
        Dictionary with protocol information
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT protocol_id, user_id, username, description, commands, created_at FROM protocol WHERE protocol_id=?",
            (protocol_id,)
        )
        row = cursor.fetchone()

        if not row:
            return {}

        return {
            "protocol_id": row[0],
            "user_id": row[1],
            "username": row[2],
            "description": row[3],
            "commands": json.loads(row[4]) if row[4] else [],
            "created_at": row[5],
        }
    finally:
        conn.close()


def list_all_runs(limit: int = 20) -> List[Dict[str, Any]]:
    """
    List all runs with summary info.

    Args:
        limit: Maximum number of results

    Returns:
        List of run summaries including raw steps/notes text (or None).
        Missing legacy columns return None; no database migration is performed.
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT r.run_id, r.protocol_id, r.created_at,
                   GROUP_CONCAT(cl.command_name) as commands, {_run_metadata_columns(conn)}
            FROM run r
            LEFT JOIN command_log cl ON r.run_id = cl.run_id
            GROUP BY r.run_id
            ORDER BY r.created_at DESC
            LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        return [
            {
                "run_id": row[0],
                "protocol_id": row[1],
                "created_at": row[2],
                "commands": row[3].split(",") if row[3] else [],
                "steps": row[4],
                "notes": row[5],
            }
            for row in rows
        ]
    finally:
        conn.close()


# Quick test
if __name__ == "__main__":
    _init_adapters()

    from adapters import AdapterRegistry

    print("=== Testing Extractor with AdapterRegistry ===\n")

    # List registered adapters
    print("1. Registered adapters:")
    for device in AdapterRegistry.list_devices():
        adapter = AdapterRegistry.get(device)
        print(f"   {device}: {type(adapter).__name__}")

    # Get latest CV
    print("\n2. Latest CV runs:")
    runs = get_runs_by_type("CV", 3)
    for run_id, step, created in runs:
        print(f"   {run_id} (step {step}) - {created}")

    # Get latest measurement
    print("\n3. Latest CV data:")
    measurements = get_latest_measurements("CV", 1)
    if measurements:
        run_id, df = measurements[0]
        print(f"   Run: {run_id}")
        print(f"   Points: {len(df)}")
        print(f"   Columns: {list(df.columns)}")
        print(f"   E range: {df[df.columns[0]].min():.3f}V to {df[df.columns[0]].max():.3f}V")
        print(f"   I range: {df[df.columns[1]].min():.6f}A to {df[df.columns[1]].max():.6f}A")

    # Get run info
    print("\n4. Run info:")
    if runs:
        info = get_run_info(runs[0][0])
        print(f"   Run: {info.get('run_id')}")
        print(f"   Protocol: {info.get('protocol_id')}")
        print(f"   Commands: {[c['name'] for c in info.get('commands', [])]}")
