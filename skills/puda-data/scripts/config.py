"""
puda-data Configuration Module

Handles project root discovery and path configuration.
Supports environment variables, config files, and automatic detection.
"""

import os
import json
from pathlib import Path
from typing import Optional

# Known markers for project root
PROJECT_MARKERS = ["puda.db", "puda.config", "project.md", "experiment.md", "protocols"]


def find_project_root(start_path: Optional[Path] = None) -> Path:
    """
    Find the project root by searching upward for known markers.

    Searches from start_path (or cwd) upward until a marker is found.

    Args:
        start_path: Starting path for search (default: current working directory)

    Returns:
        Path to project root, or start_path if no marker found
    """
    if start_path is None:
        start_path = Path.cwd()
    else:
        start_path = Path(start_path).resolve()

    # Check env var first
    if env_root := os.environ.get("PUDA_PROJECT_ROOT"):
        return Path(env_root).resolve()

    # Check puda.config in cwd and parents
    for path in [start_path, *start_path.parents]:
        # Check for puda.db
        if (path / "puda.db").exists():
            return path
        # Check for puda.config
        if (path / "puda.config").exists():
            return path
        # Check for project.md (or legacy experiment.md)
        if (path / "project.md").exists() or (path / "experiment.md").exists():
            return path
        # Check for protocols directory
        if (path / "protocols").is_dir():
            return path

    # No marker found, return cwd as fallback
    return start_path


def load_puda_config(root: Path) -> dict:
    """
    Load puda.config if it exists.

    Args:
        root: Project root path

    Returns:
        Config dict or empty dict if not found
    """
    config_path = root / "puda.config"
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# Discover project root once at module load
_PROJECT_ROOT = find_project_root()

# Derived paths
DB_PATH = _PROJECT_ROOT / "puda.db"
REPORT_DIR = _PROJECT_ROOT / "reports"
EXPORT_DIR = _PROJECT_ROOT / "exports"
LOGS_DIR = _PROJECT_ROOT / "logs"


def get_project_root() -> Path:
    """Get the discovered project root."""
    return _PROJECT_ROOT


def get_db_path() -> Path:
    """Get the database path."""
    return DB_PATH


def get_report_dir() -> Path:
    """Get the reports directory, creating it if needed."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR


def get_export_dir() -> Path:
    """Get the exports directory, creating it if needed."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR


def get_logs_dir() -> Path:
    """Get the logs directory."""
    return LOGS_DIR


def reload():
    """Force re-discovery of project root (useful for testing)."""
    global _PROJECT_ROOT, DB_PATH, REPORT_DIR, EXPORT_DIR, LOGS_DIR
    _PROJECT_ROOT = find_project_root()
    DB_PATH = _PROJECT_ROOT / "puda.db"
    REPORT_DIR = _PROJECT_ROOT / "reports"
    EXPORT_DIR = _PROJECT_ROOT / "exports"
    LOGS_DIR = _PROJECT_ROOT / "logs"
