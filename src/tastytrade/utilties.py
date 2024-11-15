import logging
from types import SimpleNamespace
from typing import Any


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging with timestamps, line numbers and module names."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s:%(name)s:%(lineno)d:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def dict_to_class(data: dict[str, Any]) -> SimpleNamespace:
    clean_data = {k.replace("-", "_"): v for k, v in data.items()}
    return SimpleNamespace(**clean_data)
