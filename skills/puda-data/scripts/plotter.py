"""
puda-data Plotter Registry

Pluggable visualization functions for different measurement types.
Uses registry pattern to allow easy extension for new plot types.
"""

import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
from typing import Dict, Callable, Optional, Any

from config import get_report_dir
from registry import SchemaRegistry
from extractor import extract_measurement_data, get_run_info


# Global plotter registry
_plotter_registry: Dict[str, Callable] = {}


def register_plotter(command: str):
    """
    Decorator to register a plotter function for a command type.

    Usage:
        @register_plotter("CV")
        def plot_cv(run_id: str, **kwargs) -> str:
            ...
    """
    def decorator(func: Callable) -> Callable:
        _plotter_registry[command.upper()] = func
        return func
    return decorator


def get_plotter(command: str) -> Optional[Callable]:
    """Get plotter function for a command type."""
    return _plotter_registry.get(command.upper())


def _get_output_path(run_id: str, prefix: str, output_path: Optional[str] = None) -> Path:
    """Generate output path for plots."""
    if output_path:
        return Path(output_path)

    reports_dir = get_report_dir()
    plots_dir = reports_dir / "plots"
    plots_dir.mkdir(exist_ok=True)
    return plots_dir / f"{prefix}_{run_id[:8]}.png"


# =============================================================================
# Built-in Plotters
# =============================================================================

@register_plotter("CV")
def plot_cv(run_id: str, output_path: str = None, title: str = "Cyclic Voltammetry (CV)") -> str:
    """
    Plot CV data as forward/backward scatter plot.

    Args:
        run_id: The run identifier
        output_path: Output file path (auto-generated if None)
        title: Plot title

    Returns:
        Path to saved plot
    """
    df = extract_measurement_data(run_id, "CV")

    if df.empty:
        raise ValueError(f"No CV data found for run {run_id}")

    # Handle different column naming conventions across devices
    # Biologic: E, I, time, Ewe, flag
    # First: potential, current, time, extra, flag
    pot_col = "potential" if "potential" in df.columns else ("E" if "E" in df.columns else df.columns[0])
    curr_col = "current" if "current" in df.columns else ("I" if "I" in df.columns else df.columns[1])

    # Separate forward and backward scans using flag column
    if "flag" in df.columns:
        forward = df[df["flag"] == 0]
        backward = df[df["flag"] == 1]
    else:
        forward = df.iloc[::2]
        backward = df.iloc[1::2]

    fig, ax = plt.subplots(figsize=(10, 8))

    ax.scatter(forward[pot_col], forward[curr_col] * 1e6,
               c="blue", s=20, alpha=0.6, label="Forward Scan")
    ax.scatter(backward[pot_col], backward[curr_col] * 1e6,
               c="red", s=20, alpha=0.6, label="Backward Scan")

    ax.set_xlabel("Potential (V)", fontsize=12)
    ax.set_ylabel("Current (µA)", fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="k", linestyle="-", linewidth=0.5)
    ax.axvline(x=0, color="k", linestyle="-", linewidth=0.5)

    plt.tight_layout()

    path = _get_output_path(run_id, "cv", output_path)
    plt.savefig(path, dpi=150)
    plt.close()

    return str(path)


@register_plotter("OCV")
def plot_ocv(run_id: str, output_path: str = None, title: str = "Open Circuit Voltage (OCV)") -> str:
    """
    Plot OCV as time series.

    Args:
        run_id: The run identifier
        output_path: Output file path
        title: Plot title

    Returns:
        Path to saved plot
    """
    df = extract_measurement_data(run_id, "OCV")

    if df.empty:
        raise ValueError(f"No OCV data found for run {run_id}")

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(df["time"], df["potential"], c="green", linewidth=1.5)

    ax.set_xlabel("Time (s)", fontsize=12)
    ax.set_ylabel("Potential (V)", fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    path = _get_output_path(run_id, "ocv", output_path)
    plt.savefig(path, dpi=150)
    plt.close()

    return str(path)


@register_plotter("PEIS")
def plot_nyquist(run_id: str, output_path: str = None, title: str = "Nyquist Plot") -> str:
    """
    Plot PEIS data as Nyquist plot (Z_real vs -Z_imag).

    Args:
        run_id: The run identifier
        output_path: Output file path
        title: Plot title

    Returns:
        Path to saved plot
    """
    df = extract_measurement_data(run_id, "PEIS")

    if df.empty:
        raise ValueError(f"No PEIS data found for run {run_id}")

    fig, ax = plt.subplots(figsize=(10, 8))

    z_imag_col = "Z_imag" if "Z_imag" in df.columns else "col_2"
    ax.scatter(df["Z_real"], -df[z_imag_col], s=20, alpha=0.7)

    ax.set_xlabel("Z_real (Ω)", fontsize=12)
    ax.set_ylabel("-Z_imag (Ω)", fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    path = _get_output_path(run_id, "nyquist", output_path)
    plt.savefig(path, dpi=150)
    plt.close()

    return str(path)


@register_plotter("CA")
def plot_ca(run_id: str, output_path: str = None, title: str = "Chronoamperometry (CA)") -> str:
    """
    Plot CA as current vs time.

    Args:
        run_id: The run identifier
        output_path: Output file path
        title: Plot title

    Returns:
        Path to saved plot
    """
    df = extract_measurement_data(run_id, "CA")

    if df.empty:
        raise ValueError(f"No CA data found for run {run_id}")

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(df["time"], df["current"] * 1e6, linewidth=1.5)

    ax.set_xlabel("Time (s)", fontsize=12)
    ax.set_ylabel("Current (µA)", fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    path = _get_output_path(run_id, "ca", output_path)
    plt.savefig(path, dpi=150)
    plt.close()

    return str(path)


def plot_default(run_id: str, command: str = "CV", output_path: str = None) -> str:
    """
    Generic plotter using first two columns.
    Falls back to this when no specialized plotter exists.

    Args:
        run_id: The run identifier
        command: Command type
        output_path: Output file path

    Returns:
        Path to saved plot
    """
    df = extract_measurement_data(run_id, command)

    if df.empty:
        raise ValueError(f"No data found for run {run_id}")

    fig, ax = plt.subplots(figsize=(10, 6))

    cols = df.columns.tolist()
    ax.scatter(df[cols[0]], df[cols[1]], s=15, alpha=0.7)

    ax.set_xlabel(cols[0], fontsize=12)
    ax.set_ylabel(cols[1], fontsize=12)
    ax.set_title(f"{command} Measurement", fontsize=14)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    path = _get_output_path(run_id, command.lower(), output_path)
    plt.savefig(path, dpi=150)
    plt.close()

    return str(path)


def plot_measurement(run_id: str, command: str = "CV", output_path: str = None) -> str:
    """
    Main entry point for plotting any measurement type.
    Routes to specialized plotter or falls back to generic.

    Args:
        run_id: The run identifier
        command: Command type (CV, OCV, PEIS, CA, etc.)
        output_path: Output file path

    Returns:
        Path to saved plot
    """
    plotter = get_plotter(command)

    if plotter:
        return plotter(run_id, output_path=output_path)

    # Fallback to generic plot
    return plot_default(run_id, command, output_path)


# =============================================================================
# Summary utilities
# =============================================================================

def get_data_summary(run_id: str, command: str = "CV") -> Dict[str, Any]:
    """
    Get summary statistics for a measurement run.

    Args:
        run_id: The run identifier
        command: Command type

    Returns:
        Dictionary with summary stats
    """
    df = extract_measurement_data(run_id, command)

    if df.empty:
        return {"run_id": run_id, "data_points": 0}

    summary = {"run_id": run_id, "data_points": len(df), "columns": list(df.columns)}

    # Add ranges for numeric columns
    for col in df.columns:
        if df[col].dtype in ["float64", "float32"]:
            summary[f"{col}_min"] = float(df[col].min())
            summary[f"{col}_max"] = float(df[col].max())

    return summary


# Quick test
if __name__ == "__main__":
    from extractor import get_runs_by_type

    print("=== Testing Plotter Registry ===\n")

    # List registered plotters
    print("Registered plotters:", list(_plotter_registry.keys()))

    # Get latest CV run
    runs = get_runs_by_type("CV", 1)
    run_id = runs[0][0]
    print(f"\nTesting with run: {run_id}")

    # Test CV plot
    print("\n1. CV Plot:")
    path = plot_measurement(run_id, "CV")
    print(f"   Saved: {path}")

    # Test summary
    print("\n2. Data Summary:")
    summary = get_data_summary(run_id)
    for k, v in summary.items():
        print(f"   {k}: {v}")
