"""
Click CLI for TastyTrade market data subscription management.

This module implements the `tasty-subscription` CLI tool with `run` and `status`
subcommands for managing market data feeds.
"""

import logging
import sys
from datetime import datetime

import click

from tastytrade.common.logging import setup_logging

# Valid log levels for validation
VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

# Valid candle intervals
VALID_INTERVALS = ["1d", "1h", "30m", "15m", "5m", "m"]


def validate_date(_ctx: click.Context, _param: click.Parameter, value: str) -> datetime:
    """Validate and parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise click.BadParameter(
            f"Invalid date format: '{value}'. Expected YYYY-MM-DD (e.g., 2026-01-15)"
        ) from None


def validate_symbols(
    _ctx: click.Context, _param: click.Parameter, value: str
) -> list[str]:
    """Validate and parse comma-separated symbols."""
    if not value or not value.strip():
        raise click.BadParameter("Symbols cannot be empty")

    symbols = [s.strip() for s in value.split(",") if s.strip()]

    if not symbols:
        raise click.BadParameter("At least one symbol is required")

    return symbols


def validate_intervals(
    _ctx: click.Context, _param: click.Parameter, value: str
) -> list[str]:
    """Validate and parse comma-separated intervals."""
    if not value or not value.strip():
        raise click.BadParameter("Intervals cannot be empty")

    intervals = [i.strip() for i in value.split(",") if i.strip()]

    if not intervals:
        raise click.BadParameter("At least one interval is required")

    invalid = [i for i in intervals if i not in VALID_INTERVALS]
    if invalid:
        raise click.BadParameter(
            f"Invalid interval(s): {', '.join(invalid)}. "
            f"Valid intervals: {', '.join(VALID_INTERVALS)}"
        )

    return intervals


def validate_log_level(_ctx: click.Context, _param: click.Parameter, value: str) -> str:
    """Validate log level."""
    value_upper = value.upper()
    if value_upper not in VALID_LOG_LEVELS:
        raise click.BadParameter(
            f"Invalid log level: '{value}'. "
            f"Valid levels: {', '.join(VALID_LOG_LEVELS)}"
        )
    return value_upper


@click.group()
@click.version_option(version="0.1.0", prog_name="tasty-subscription")
def cli() -> None:
    """TastyTrade Market Data Subscription CLI.

    Manage market data subscriptions including historical backfill,
    live streaming, and operational monitoring.

    \b
    Commands:
      run     Start the feed process with specified configuration
      status  Query the status of active subscriptions
    """
    pass


@cli.command()
@click.option(
    "--start-date",
    required=True,
    callback=validate_date,
    help="Date to begin historical backfill (format: YYYY-MM-DD)",
)
@click.option(
    "--symbols",
    required=True,
    callback=validate_symbols,
    help="Comma-separated list of symbols (e.g., AAPL,SPY,QQQ)",
)
@click.option(
    "--intervals",
    required=True,
    callback=validate_intervals,
    help=f"Comma-separated list of candle intervals. Valid: {', '.join(VALID_INTERVALS)}",
)
@click.option(
    "--log-level",
    default="INFO",
    callback=validate_log_level,
    help="Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO",
)
def run(
    start_date: datetime,
    symbols: list[str],
    intervals: list[str],
    log_level: str,
) -> None:
    """Start the feed process with specified configuration.

    This command initializes the market data feed process with historical
    backfill from START_DATE, subscribes to live feeds for the specified
    SYMBOLS and INTERVALS, and runs until interrupted.

    \b
    Example:
      tasty-subscription run --start-date 2026-01-15 --symbols AAPL,SPY --intervals 1d,1h,5m
    """
    # Initialize logging
    log_level_int = getattr(logging, log_level)
    setup_logging(level=log_level_int, console=True, file=False)
    logger = logging.getLogger(__name__)

    # Display startup banner
    logger.info("=" * 60)
    logger.info("TastyTrade Market Data Subscription - Starting")
    logger.info("=" * 60)
    logger.info("Configuration:")
    logger.info(f"  Start Date:  {start_date.strftime('%Y-%m-%d')}")
    logger.info(f"  Symbols:     {', '.join(symbols)}")
    logger.info(f"  Intervals:   {', '.join(intervals)}")
    logger.info(f"  Log Level:   {log_level}")
    logger.info(f"  Feed Count:  {len(symbols) * len(intervals)} candle feeds")
    logger.info("=" * 60)

    # Placeholder for orchestration (implemented in later stories)
    logger.info("Feed process initialized successfully")
    logger.info("Orchestration not yet implemented - exiting cleanly")
    logger.info("See TT-7 through TT-12 for remaining implementation")

    sys.exit(0)


@cli.command()
def status() -> None:
    """Query the status of active subscriptions.

    This command queries the Redis subscription store and displays
    information about active market data feeds, including:

    \b
    - Active subscriptions by feed type (candles, quotes, trades, greeks)
    - Last message timestamp per feed
    - Connection health (DXLink, InfluxDB, Redis)
    - Error summary if any

    \b
    Example:
      tasty-subscription status
    """
    click.echo("Status command not yet implemented")
    click.echo("See TT-11 for implementation details")
    sys.exit(0)


def main() -> None:
    """Entry point for the tasty-subscription CLI."""
    cli()


if __name__ == "__main__":
    main()
