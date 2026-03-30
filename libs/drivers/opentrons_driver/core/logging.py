"""Logging configuration for the opentrons-driver package.

Mirrors the puda-drivers logging pattern: optional file output to a logs/ folder
alongside console output. Configure once at the start of your script.

Example::

    from opentrons_driver.core.logging import setup_logging
    import logging

    setup_logging(enable_file_logging=True, log_level=logging.DEBUG, log_file_name="experiment")
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path


def setup_logging(
    enable_file_logging: bool = False,
    log_level: int = logging.DEBUG,
    logs_folder: str = "logs",
    log_file_name: str | None = None,
) -> None:
    """Configure logging for the opentrons-driver package.

    Args:
        enable_file_logging: If ``True``, write logs to a file inside
            *logs_folder* in addition to the console.  Defaults to ``False``
            (console only).
        log_level: Standard :mod:`logging` level constant, e.g.
            ``logging.DEBUG``, ``logging.INFO``.  Defaults to
            ``logging.DEBUG``.
        logs_folder: Directory name for log files.  Created automatically if
            it does not exist.  Defaults to ``"logs"``.
        log_file_name: Base name for the log file.  The ``.log`` extension is
            appended automatically if omitted.  When ``None`` or empty a
            timestamp-based name is used, e.g. ``log_20260325_120000.log``.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers so calling this function more than once
    # does not duplicate output.
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if enable_file_logging:
        log_dir = Path(logs_folder)
        log_dir.mkdir(parents=True, exist_ok=True)

        if log_file_name:
            name = log_file_name if log_file_name.endswith(".log") else f"{log_file_name}.log"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"log_{timestamp}.log"

        file_path = log_dir / name
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        logging.getLogger(__name__).debug("File logging enabled: %s", file_path)
