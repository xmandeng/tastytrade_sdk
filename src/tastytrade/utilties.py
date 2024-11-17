import logging
from types import SimpleNamespace
from typing import Any


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging with line numbers and module names."""
    # Clear any existing handlers to avoid duplicate logs
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.handlers.clear()

    # Configure basic logging
    logging.basicConfig(
        level=level,
        format="%(levelname)s:%(name)s:%(lineno)d:%(message)s",
        force=True,  # This ensures the configuration is applied
    )


def dict_to_class(data: dict[str, Any]) -> SimpleNamespace:
    clean_data = {k.replace("-", "_"): v for k, v in data.items()}
    return SimpleNamespace(**clean_data)
