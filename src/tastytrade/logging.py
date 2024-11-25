import logging


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging with timestamps, line numbers and module names."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s:%(name)s:%(lineno)d:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
