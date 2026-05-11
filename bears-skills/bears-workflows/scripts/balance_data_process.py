"""
Balance data processing utilities for viscosity optimization workflows.

The raw data stream stores balance readings in mg and protocol command timing.
This module can merge protocol commands onto balance readings, process the
aspiration-to-delay window, generate a normalized mass-change CSV, and compute
summary metrics for the optimizer.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional runtime dependency
    np = None

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional runtime dependency
    pd = None

try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover - optional runtime dependency
    plt = None


IMPORTANT_COMMANDS = {"aspirate", "dispense"}
DEFAULT_COMMAND_TOLERANCE_SECONDS = 0.5
DEFAULT_OUTLIER_THRESHOLD_MG = 10000.0
DEFAULT_PROCESSING_WINDOW_SECONDS = 30.0


def _require_pandas() -> bool:
    if pd is None:
        print("Cannot process balance data: pandas is not installed")
        return False
    return True


def _require_numpy() -> bool:
    if np is None:
        print("Cannot process balance data: numpy is not installed")
        return False
    return True


def _reading_time(reading: dict[str, Any]) -> float:
    return float(reading.get("time", reading.get("timestamp", 0.0)))


def _ensure_mass_mg_columns(df: Any) -> Any:
    """Ensure a dataframe has a numeric mass_mg column."""
    if "mass_mg" in df.columns:
        df["mass_mg"] = pd.to_numeric(df["mass_mg"], errors="coerce")
        return df
    if "mass_g" in df.columns:
        df["mass_mg"] = pd.to_numeric(df["mass_g"], errors="coerce") * 1000.0
        return df
    raise ValueError("Expected a 'mass_mg' column, or 'mass_g' to convert from grams.")


def _set_command_row(df: Any, row_idx: int, command: dict[str, Any]) -> None:
    df.at[row_idx, "command_type"] = command.get("command_type", "")
    df.at[row_idx, "command_volume_uL"] = command.get("volume", "")
    df.at[row_idx, "command_location"] = command.get("location", "")
    df.at[row_idx, "command_duration_sec"] = command.get("seconds", "")


def merge_protocol_commands_with_balance_readings(
    csv_path: str | Path,
    balance_readings: list[dict[str, Any]],
    protocol_commands: list[dict[str, Any]],
    balance_start_time: float,
    protocol_start_time: float,
):
    """
    Merge protocol commands with balance readings in an existing CSV file.

    Commands are matched to balance readings by elapsed time. Delay commands mark
    every reading within the delay window when possible. Aspirate and dispense
    commands can overwrite delay labels because they are the key commands for
    viscosity analysis.
    """
    if not _require_pandas():
        return None

    try:
        csv_path = Path(csv_path)
        df = pd.read_csv(csv_path)
        df = _ensure_mass_mg_columns(df)

        time_offset = float(protocol_start_time) - float(balance_start_time)

        df["command_type"] = ""
        df["command_volume_uL"] = ""
        df["command_location"] = ""
        df["command_duration_sec"] = ""

        matched_commands: set[int] = set()
        sorted_commands = sorted(
            protocol_commands,
            key=lambda command: float(command.get("elapsed_time", 0.0)),
        )

        for command in sorted_commands:
            command_type = command.get("command_type", "")
            if not command_type:
                continue

            command_time = float(command.get("elapsed_time", 0.0)) + time_offset

            if command_type == "delay":
                try:
                    delay_duration = float(command.get("seconds") or 0.0)
                except (TypeError, ValueError):
                    delay_duration = 0.0

                delay_start = command_time
                delay_end = delay_start + delay_duration

                for idx, reading in enumerate(balance_readings):
                    if idx >= len(df):
                        break
                    reading_time = _reading_time(reading)
                    if delay_start <= reading_time <= delay_end:
                        current_command = df.at[idx, "command_type"]
                        if current_command in ("", "delay"):
                            df.at[idx, "command_type"] = command_type
                            df.at[idx, "command_duration_sec"] = (
                                delay_duration if delay_duration > 0 else ""
                            )
                            matched_commands.add(id(command))

                if id(command) not in matched_commands and balance_readings:
                    closest_idx = _closest_reading_index(
                        balance_readings,
                        command_time,
                        tolerance_seconds=DEFAULT_COMMAND_TOLERANCE_SECONDS,
                    )
                    if closest_idx is not None and closest_idx < len(df):
                        current_command = df.at[closest_idx, "command_type"]
                        if current_command in ("", "delay"):
                            df.at[closest_idx, "command_type"] = command_type
                            df.at[closest_idx, "command_duration_sec"] = (
                                delay_duration if delay_duration > 0 else ""
                            )
                            matched_commands.add(id(command))
                continue

            closest_idx = _closest_reading_index(
                balance_readings,
                command_time,
                tolerance_seconds=DEFAULT_COMMAND_TOLERANCE_SECONDS,
            )

            if closest_idx is None and command_type in IMPORTANT_COMMANDS and balance_readings:
                closest_idx = min(
                    range(len(balance_readings)),
                    key=lambda idx: abs(_reading_time(balance_readings[idx]) - command_time),
                )

            if closest_idx is None or closest_idx >= len(df):
                continue

            current_command_type = df.at[closest_idx, "command_type"]
            if current_command_type == "" or (
                command_type in IMPORTANT_COMMANDS and current_command_type == "delay"
            ):
                _set_command_row(df, closest_idx, command)
                matched_commands.add(id(command))

        df.to_csv(csv_path, index=False)

        matched_count = len(matched_commands)
        total_commands = len(protocol_commands)
        print(f"Merged {matched_count}/{total_commands} protocol commands with balance readings")
        if matched_count < total_commands:
            print(f"{total_commands - matched_count} commands could not be matched")
        return df
    except Exception as exc:  # pragma: no cover - preserves diagnostic behavior
        print(f"Error merging protocol commands: {exc}")
        return None


def _closest_reading_index(
    balance_readings: list[dict[str, Any]],
    target_time: float,
    *,
    tolerance_seconds: float,
) -> int | None:
    closest_idx: int | None = None
    min_diff = float("inf")

    for idx, reading in enumerate(balance_readings):
        diff = abs(_reading_time(reading) - target_time)
        if diff < min_diff and diff <= tolerance_seconds:
            min_diff = diff
            closest_idx = idx

    return closest_idx


def analyze_viscosity_data(
    csv_file_path: str | Path,
    output_dir: str | Path,
    *,
    outlier_threshold_mg: float = DEFAULT_OUTLIER_THRESHOLD_MG,
    window_seconds: float = DEFAULT_PROCESSING_WINDOW_SECONDS,
):
    """
    Process one raw viscosity CSV into normalized time and mass-change data.

    Processing steps:
    1. Strip apostrophes from serial output.
    2. Convert mass_g to mass_mg if needed.
    3. Remove rows below outlier_threshold_mg.
    4. Select data from the first aspirate command to the last delay after it.
    5. Average delay-period readings per second.
    6. Normalize time and mass to start at 0.
    7. Keep 0-window_seconds and extend the final value if the run is shorter.
    8. Save the processed CSV with the same filename in output_dir.
    """
    if not (_require_pandas() and _require_numpy()):
        return None

    csv_file_path = Path(csv_file_path)
    print(f"Processing: {csv_file_path}")

    try:
        content = csv_file_path.read_text(encoding="utf-8").replace("'", "")
        df = pd.read_csv(StringIO(content))
        df = _ensure_mass_mg_columns(df)
    except Exception as exc:
        print(f"Error reading or parsing CSV file: {exc}")
        return None

    if "command_type" not in df.columns:
        print(f"Error: 'command_type' column not found. Available columns: {list(df.columns)}")
        return None
    if "time" not in df.columns:
        print(f"Error: 'time' column not found. Available columns: {list(df.columns)}")
        return None

    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    df = df.dropna(subset=["time", "mass_mg"]).copy()
    df_cleaned = df[df["mass_mg"] >= float(outlier_threshold_mg)].copy()

    if df_cleaned.empty:
        print(f"Warning: no data remains after filtering mass_mg < {outlier_threshold_mg}")
        return None

    aspirate_indices = df_cleaned[df_cleaned["command_type"] == "aspirate"].index
    if len(aspirate_indices) == 0:
        unique_commands = df_cleaned["command_type"].dropna().unique()
        print(f"Warning: no 'aspirate' command found in {csv_file_path}")
        print(f"Available command types: {unique_commands}")
        return None

    aspirate_start_idx = aspirate_indices[0]
    aspirate_time = df_cleaned.loc[aspirate_start_idx, "time"]

    delay_indices = df_cleaned[df_cleaned["command_type"] == "delay"].index
    delay_indices_after_aspirate = delay_indices[delay_indices > aspirate_start_idx]
    if len(delay_indices_after_aspirate) == 0:
        print(f"Warning: no 'delay' command found after 'aspirate' in {csv_file_path}")
        return None

    first_delay_idx = delay_indices_after_aspirate[0]
    last_delay_idx = delay_indices_after_aspirate[-1]
    first_delay_time = df_cleaned.loc[first_delay_idx, "time"]
    last_delay_time = df_cleaned.loc[last_delay_idx, "time"]

    df_aspirate_to_delay = df_cleaned[
        (df_cleaned["time"] >= aspirate_time)
        & (df_cleaned["time"] < first_delay_time)
    ].copy()
    df_delay_range = df_cleaned[
        (df_cleaned["time"] >= first_delay_time)
        & (df_cleaned["time"] <= last_delay_time)
    ].copy()

    if df_delay_range.empty:
        print(f"Warning: no data in delay range for {csv_file_path}")
        return None

    df_delay_range["time_second"] = df_delay_range["time"].round().astype(int)
    df_delay_averaged = (
        df_delay_range.groupby("time_second")
        .agg({"time": "mean", "mass_mg": "mean"})
        .reset_index(drop=True)
    )

    frames = []
    if not df_aspirate_to_delay.empty:
        frames.append(df_aspirate_to_delay[["time", "mass_mg"]])
    frames.append(df_delay_averaged[["time", "mass_mg"]])

    df_combined = pd.concat(frames, ignore_index=True).sort_values("time")
    df_combined = df_combined.reset_index(drop=True)

    if df_combined.empty:
        print(f"Warning: no data after combining for {csv_file_path}")
        return None

    result_df = _normalize_and_window_data(
        df_combined["time"].to_numpy(),
        df_combined["mass_mg"].to_numpy(),
        window_seconds=float(window_seconds),
    )
    if result_df is None:
        print(f"Warning: no data remains after filtering to 0-{window_seconds}s")
        return None

    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / csv_file_path.name
        result_df.to_csv(output_path, index=False)
    except Exception as exc:
        print(f"Error saving processed CSV: {exc}")
        return None

    print(f"Saved processed data to: {output_path}")
    print(
        "Data points: "
        f"{len(result_df)}, Time range: {result_df['Time'].min():.2f}s "
        f"to {result_df['Time'].max():.2f}s"
    )
    print(
        "Mass range: "
        f"{result_df['Weight'].min():.2f} mg to {result_df['Weight'].max():.2f} mg"
    )
    return result_df


def _normalize_and_window_data(times: Any, masses_mg: Any, *, window_seconds: float):
    if len(times) == 0:
        return None

    normalized_times = times - times[0]
    normalized_masses = masses_mg - masses_mg[0]

    time_mask = (normalized_times >= 0) & (normalized_times <= window_seconds)
    normalized_times = normalized_times[time_mask]
    normalized_masses = normalized_masses[time_mask]

    if len(normalized_times) == 0:
        return None

    normalized_times[0] = 0.0
    normalized_masses[0] = 0.0

    last_time = normalized_times[-1]
    last_mass = normalized_masses[-1]
    if last_time < window_seconds:
        if len(normalized_times) > 1:
            time_step = float(np.mean(np.diff(normalized_times)))
            if time_step <= 0:
                time_step = 1.0
        else:
            time_step = 1.0

        extension_times = np.arange(last_time + time_step, window_seconds + time_step, time_step)
        extension_times = extension_times[extension_times <= window_seconds]
        extension_masses = np.full_like(extension_times, last_mass)

        normalized_times = np.concatenate([normalized_times, extension_times])
        normalized_masses = np.concatenate([normalized_masses, extension_masses])
        print(f"Extended data from {last_time:.2f}s to {window_seconds:.2f}s")

    return pd.DataFrame({"Time": normalized_times, "Weight": normalized_masses})


def analyze_latest_viscosity_experiment(
    csv_file_path: str | Path | None = None,
    base_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Analyze a viscosity experiment CSV, defaulting to the latest raw CSV.
    """
    if not _require_pandas():
        return {"success": False, "message": "pandas not installed"}

    if csv_file_path is None:
        raw_data_dir = Path("reports") / "viscosity_raw_data"
        if not raw_data_dir.exists():
            return {
                "success": False,
                "message": f"Directory '{raw_data_dir}' not found.",
            }

        csv_files = list(raw_data_dir.glob("*.csv"))
        if not csv_files:
            return {
                "success": False,
                "message": f"No CSV files found in '{raw_data_dir}'.",
            }

        csv_file_path = max(csv_files, key=lambda path: path.stat().st_mtime)
        print(f"Found latest CSV file: {csv_file_path}")

    csv_file_path = Path(csv_file_path)

    if base_output_dir is None:
        processed_dir = Path("reports") / "viscosity_processed_data"
    else:
        processed_dir = Path(base_output_dir) / "viscosity_processed_data"

    try:
        processed_dir = processed_dir.resolve()
        processed_dir.mkdir(parents=True, exist_ok=True)
        print(f"Processed data directory: {processed_dir}")
    except Exception as exc:
        return {
            "success": False,
            "message": f"Failed to create output directory: {exc}",
        }

    result_df = analyze_viscosity_data(csv_file_path, processed_dir)
    if result_df is None:
        return {"success": False, "message": "Failed to analyze viscosity data"}
    if result_df.empty:
        return {"success": False, "message": "No data points after processing"}

    max_weight = float(result_df["Weight"].max())
    min_weight = float(result_df["Weight"].min())
    weight_change = max_weight - min_weight

    return {
        "success": True,
        "message": "Analysis complete",
        "data_points": len(result_df),
        "max_weight_mg": max_weight,
        "min_weight_mg": min_weight,
        "weight_change_mg": weight_change,
        "processed_csv_path": str(processed_dir / csv_file_path.name),
        "source_csv_path": str(csv_file_path),
        "result_df": result_df,
    }


def plot_and_save_viscosity_graph(
    result_df: Any,
    csv_file_path: str | Path,
    graph_output_dir: str | Path | None = None,
) -> str | None:
    """
    Plot normalized mass change vs time and save it as a PNG.
    """
    if plt is None:
        print("Cannot plot: matplotlib is not installed")
        return None
    if result_df is None or len(result_df) == 0:
        print("No data to plot")
        return None

    if graph_output_dir is None:
        graph_output_dir = Path("reports") / "viscosity_graphs"
    else:
        graph_output_dir = Path(graph_output_dir)

    try:
        graph_output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"Error creating graph output directory: {exc}")
        return None

    csv_file_path = Path(csv_file_path)
    graph_path = graph_output_dir / f"{csv_file_path.stem}_graph.png"

    try:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(
            result_df["Time"],
            result_df["Weight"],
            linewidth=2,
            color="#2ecc71",
            marker="o",
            markersize=3,
        )
        ax.set_xlabel("Time (s)", fontsize=12)
        ax.set_ylabel("Relative Mass Change (mg)", fontsize=12)
        ax.set_title("Normalized Mass Change vs Time", fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, min(30, max(1.0, float(result_df["Time"].max()))))
        fig.tight_layout()
        fig.savefig(graph_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as exc:
        print(f"Error saving graph: {exc}")
        plt.close("all")
        return None

    print(f"Graph saved to: {graph_path}")
    return str(graph_path)


def analyze_balance_data(
    balance_readings: list[dict[str, Any]],
    target_mass: float | None = None,
) -> dict[str, Any] | None:
    """Analyze balance readings and calculate mass-change and error metrics in mg."""
    if not balance_readings or not _require_pandas():
        return None

    df = pd.DataFrame(balance_readings)
    if df.empty:
        return None

    df = _ensure_mass_mg_columns(df)
    max_weight = float(df["mass_mg"].max())
    min_weight = float(df["mass_mg"].min())
    relative_mass_change = max_weight - min_weight

    mass_error = None
    if target_mass is not None and target_mass > 0:
        mass_error = float(target_mass) - relative_mass_change

    return {
        "relative_mass_change_mg": relative_mass_change,
        "mass_error_mg": mass_error,
        "max_weight_mg": max_weight,
        "min_weight_mg": min_weight,
        "readings_count": len(df),
    }


def calculate_signed_error(actual_mass_change_mg: float, target_mass_mg: float) -> float:
    """
    Calculate signed error between actual and target mass change (mg).

    Positive means over-transfer; negative means under-transfer.
    """
    return float(actual_mass_change_mg) - float(target_mass_mg)
