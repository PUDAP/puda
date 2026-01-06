"""
Logging configuration utility.

This module provides a function to configure logging with optional file output
to a logs folder.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(
    enable_file_logging: bool = False,
    log_level: int = logging.DEBUG,
    logs_folder: str = "logs",
    log_file_name: Optional[str] = None,
) -> None:
    """
    Configure logging with optional file output to a logs folder.

    Args:
        enable_file_logging: If True, logs will be written to files in the logs folder.
                           If False, logs will only be output to console.
        log_level: Logging level constant from logging module (e.g., logging.DEBUG,
                   logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL).
                   Defaults to logging.DEBUG.
        logs_folder: Name of the folder to store log files (default: "logs")
        log_file_name: Custom name for the log file. If None or empty string, uses
                      timestamp-based name. If provided without .log extension, it will
                      be added automatically.
    """
    # Create logs folder if file logging is enabled
    if enable_file_logging:
        log_dir = Path(logs_folder)
        log_dir.mkdir(exist_ok=True)
        
        # Create a log file with custom name or timestamp
        if log_file_name and log_file_name.strip():  # None or empty/whitespace strings use timestamp
            # Ensure .log extension if not present
            if not log_file_name.endswith(".log"):
                log_file_name = f"{log_file_name}.log"
            log_file = log_dir / log_file_name
        else:
            # Default: timestamp-based name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = log_dir / f"log_{timestamp}.log"
        
        # Configure logging with both console and file handlers
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),  # Console output
                logging.FileHandler(log_file, mode="w"),  # File output
            ],
        )
        
        # Log that file logging is enabled
        logger = logging.getLogger(__name__)
        logger.info("File logging enabled. Log file: %s", log_file)
    else:
        # Configure logging with only console handler
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()],  # Console output only
        )
        
        # Log that file logging is disabled
        logger = logging.getLogger(__name__)
        logger.info("File logging disabled. Logs will only be output to console.")
