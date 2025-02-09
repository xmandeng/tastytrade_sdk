import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(
    level: int = logging.INFO,
    log_dir: Optional[str] = None,
    filename_prefix: str = "tastytrade",
    console: bool = True,
    file: bool = True,
) -> None:
    """Configure logging with timestamps, line numbers and module names.

    Args:
        level: The logging level to use (default: logging.INFO)
        log_dir: Directory to store log files (default: ./logs)
        filename_prefix: Prefix for log filename (default: 'tastytrade')
        console: Whether to output logs to console (default: True)
        file: Whether to output logs to file (default: True)
    """
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Common format for all handlers
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s:%(name)s:%(lineno)d:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler
    if file:
        # Default log directory if none specified
        if log_dir is None:
            log_dir = os.path.join(os.getcwd(), "logs")

        # Create log directory if it doesn't exist
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(log_dir, f"{filename_prefix}_{timestamp}.log")

        # Create and add file handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Log the initialization
        root_logger.info("Logging initialized - writing to %s", log_file)
