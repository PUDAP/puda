"""
puda-data Phase 4: Visualizer

Pluggable visualization functions for reports.
"""

import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from typing import Optional

from extractor import extract_measurement_data, get_run_info
from hasher import generate_fingerprint
from config import get_report_dir


def plot_cv(
    run_id: str,
    output_path: str = None,
    title: str = "Cyclic Voltammetry (CV) Curve"
) -> str:
    """
    Plot CV data as scatter plot.

    Args:
        run_id: The run identifier
        output_path: Output file path (auto-generated if None)
        title: Plot title

    Returns:
        Path to saved plot
    """
    # Get data
    df = extract_measurement_data(run_id, "CV")

    if df.empty:
        raise ValueError(f"No CV data found for run {run_id}")

    # Separate forward and backward scans
    forward = df[df['flag'] == 0]
    backward = df[df['flag'] == 1]

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    # Plot both directions with different colors
    ax.scatter(forward['potential'], forward['current'] * 1e6,
               c='blue', s=20, alpha=0.6, label='Forward Scan')
    ax.scatter(backward['potential'], backward['current'] * 1e6,
               c='red', s=20, alpha=0.6, label='Backward Scan')

    ax.set_xlabel('Potential (V)', fontsize=12)
    ax.set_ylabel('Current (µA)', fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
    ax.axvline(x=0, color='k', linestyle='-', linewidth=0.5)

    plt.tight_layout()

    # Save
    if output_path is None:
        # Default path
        reports_dir = get_report_dir()
        plots_dir = reports_dir / "plots"
        plots_dir.mkdir(exist_ok=True)
        output_path = plots_dir / f"cv_{run_id[:8]}.png"

    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"Plot saved: {output_path}")
    return str(output_path)


def plot_cv_simple(
    run_id: str,
    output_path: str = None,
    title: str = "CV Curve"
) -> str:
    """
    Simple CV plot (single color).

    Args:
        run_id: The run identifier
        output_path: Output file path
        title: Plot title

    Returns:
        Path to saved plot
    """
    df = extract_measurement_data(run_id, "CV")

    if df.empty:
        raise ValueError(f"No CV data found for run {run_id}")

    plt.figure(figsize=(10, 6))
    plt.scatter(df['potential'], df['current'] * 1e6,
                c=range(len(df)), cmap='viridis', s=15, alpha=0.7)
    plt.colorbar(label='Scan Order')
    plt.xlabel('Potential (V)')
    plt.ylabel('Current (µA)')
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    if output_path is None:
        reports_dir = get_report_dir()
        plots_dir = reports_dir / "plots"
        plots_dir.mkdir(exist_ok=True)
        output_path = plots_dir / f"cv_{run_id[:8]}.png"

    plt.savefig(output_path, dpi=150)
    plt.close()

    return str(output_path)


def plot_histogram(
    run_id: str,
    column: str = "current",
    output_path: str = None,
    title: str = None
) -> str:
    """
    Plot histogram of a data column.

    Args:
        run_id: The run identifier
        column: Column to histogram ('current' or 'potential')
        output_path: Output file path
        title: Plot title

    Returns:
        Path to saved plot
    """
    df = extract_measurement_data(run_id, "CV")

    if df.empty:
        raise ValueError(f"No data found for run {run_id}")

    if title is None:
        title = f"{column.capitalize()} Distribution"

    plt.figure(figsize=(8, 5))
    plt.hist(df[column] * 1e6, bins=30, edgecolor='black', alpha=0.7)
    plt.xlabel(f'{column.capitalize()} (µA)' if column == 'current' else f'{column.capitalize()} (V)')
    plt.ylabel('Frequency')
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    if output_path is None:
        reports_dir = get_report_dir()
        plots_dir = reports_dir / "plots"
        plots_dir.mkdir(exist_ok=True)
        output_path = plots_dir / f"hist_{column}_{run_id[:8]}.png"

    plt.savefig(output_path, dpi=150)
    plt.close()

    return str(output_path)


def get_data_summary(run_id: str) -> dict:
    """
    Get summary statistics for a run.

    Args:
        run_id: The run identifier

    Returns:
        Dictionary with summary stats
    """
    df = extract_measurement_data(run_id, "CV")
    fp = generate_fingerprint(run_id)

    return {
        "run_id": run_id,
        "data_points": len(df),
        "potential_min": float(df['potential'].min()),
        "potential_max": float(df['potential'].max()),
        "current_min": float(df['current'].min()),
        "current_max": float(df['current'].max()),
        "current_mean": float(df['current'].mean()),
        "current_std": float(df['current'].std()),
    }


# Quick test
if __name__ == "__main__":
    from extractor import get_runs_by_type

    print("=== Testing Visualizer ===\n")

    runs = get_runs_by_type("CV", 1)
    run_id = runs[0][0]

    # Test CV plot
    print("1. CV Plot:")
    path = plot_cv(run_id)
    print(f"   Saved: {path}")

    # Test histogram
    print("\n2. Current Histogram:")
    path = plot_histogram(run_id, "current")
    print(f"   Saved: {path}")

    # Test summary
    print("\n3. Data Summary:")
    summary = get_data_summary(run_id)
    for k, v in summary.items():
        print(f"   {k}: {v}")
