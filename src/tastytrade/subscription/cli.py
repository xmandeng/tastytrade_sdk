"""
Click CLI for TastyTrade market data subscription management.

This module implements the `tasty-subscription` CLI tool with `run` and `status`
subcommands for managing market data feeds.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

import click

from tastytrade.common.logging import setup_logging
from tastytrade.common.observability import init_observability, shutdown_observability
from tastytrade.subscription.orchestrator import run_subscription
from tastytrade.subscription.status import format_status, query_status

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
@click.option(
    "--health-interval",
    default=3600,
    type=int,
    help="Seconds between health status log entries. Default: 3600 (1 hour)",
)
def run(
    start_date: datetime,
    symbols: list[str],
    intervals: list[str],
    log_level: str,
    health_interval: int,
) -> None:
    """Start the feed process with specified configuration.

    This command initializes the market data feed process with historical
    backfill from START_DATE, subscribes to live feeds for the specified
    SYMBOLS and INTERVALS, and runs until interrupted.

    \b
    Example:
      tasty-subscription run --start-date 2026-01-15 --symbols AAPL,SPY --intervals 1d,1h,5m
    """
    # Initialize logging - use observability module if Grafana Cloud is configured
    os.environ["LOG_LEVEL"] = log_level
    if os.getenv("GRAFANA_CLOUD_TOKEN"):
        init_observability()
        logger = logging.getLogger(__name__)
        logger.info("Grafana Cloud logging enabled")
    else:
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
    logger.info(f"  Health Int:  {health_interval}s")
    logger.info("=" * 60)

    # Run the orchestration
    try:
        asyncio.run(
            run_subscription(
                symbols=symbols,
                intervals=intervals,
                start_date=start_date,
                health_interval=health_interval,
            )
        )
    except KeyboardInterrupt:
        logger.info("Received interrupt signal - shutting down")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        # Ensure logs are flushed to Grafana Cloud before exit
        if os.getenv("GRAFANA_CLOUD_TOKEN"):
            shutdown_observability()

    sys.exit(0)


@cli.command()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output in JSON format for machine consumption.",
)
def status(as_json: bool) -> None:
    """Query the status of active subscriptions.

    This command queries the Redis subscription store and displays
    information about active market data feeds, including:

    \b
    - Active subscriptions by feed type (candles, tickers)
    - Last message timestamp per feed
    - Connection health (Redis)

    \b
    Example:
      tasty-subscription status
      tasty-subscription status --json
    """
    result = asyncio.run(query_status())
    click.echo(format_status(result, as_json=as_json))


@cli.command(name="account-stream")
@click.option(
    "--log-level",
    default="INFO",
    callback=validate_log_level,
    help="Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO",
)
@click.option(
    "--health-interval",
    default=3600,
    type=int,
    help="Seconds between health status log entries. Default: 3600",
)
def account_stream(log_level: str, health_interval: int) -> None:
    """Start the account event stream, publishing positions and balances to Redis.

    Connects to the TastyTrade Account Streamer WebSocket,
    publishes CurrentPosition and AccountBalance events to Redis,
    and self-heals on connection failures.

    \b
    Example:
      tasty-subscription account-stream
      tasty-subscription account-stream --log-level DEBUG
    """
    os.environ["LOG_LEVEL"] = log_level
    if os.getenv("GRAFANA_CLOUD_TOKEN"):
        init_observability()
        local_logger = logging.getLogger(__name__)
        local_logger.info("Grafana Cloud logging enabled")
    else:
        log_level_int = getattr(logging, log_level)
        setup_logging(level=log_level_int, console=True, file=False)
        local_logger = logging.getLogger(__name__)

    local_logger.info("=" * 60)
    local_logger.info("TastyTrade Account Stream - Starting")
    local_logger.info("=" * 60)

    from tastytrade.accounts.orchestrator import run_account_stream

    try:
        asyncio.run(run_account_stream(health_interval=health_interval))
    except KeyboardInterrupt:
        local_logger.info("Received interrupt signal - shutting down")
    except Exception as e:
        local_logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        if os.getenv("GRAFANA_CLOUD_TOKEN"):
            shutdown_observability()

    sys.exit(0)


@cli.command(name="positions")
def positions_cmd() -> None:
    """Show current position metrics from Redis.

    Reads positions, quotes, and Greeks from Redis and displays
    a joined DataFrame. Requires account-stream and subscribe
    to be running.

    \b
    Example:
      tasty-subscription positions
    """

    async def _run() -> None:
        from tastytrade.analytics.positions import PositionMetricsReader

        reader = PositionMetricsReader()
        try:
            df = await reader.read()
            if df.empty:
                click.echo("No positions found in Redis. Is account-stream running?")
                return
            display_cols = [
                "underlying_symbol",
                "symbol",
                "instrument_type",
                "quantity",
                "quantity_direction",
                "mid_price",
                "entry_price",
                "entry_value",
                "multiplier",
                "fees",
                "dte",
                "delta",
                "dollar_theta",
                "implied_volatility",
                "rolls",
                "realized_pnl",
                "chain_fees",
                "tt_strategy",
            ]
            available = [c for c in display_cols if c in df.columns]
            sort_cols = [c for c in ["underlying_symbol", "symbol"] if c in df.columns]
            if sort_cols:
                df = df.sort_values(sort_cols)
            click.echo(df[available].astype(object).fillna("").to_string(index=False))
        finally:
            await reader.close()

    asyncio.run(_run())


@cli.command(name="positions-summary")
def positions_summary_cmd() -> None:
    """Show positions aggregated by underlying with net delta.

    Pre-aggregates position data in Python for fast output.
    Pipe to an LLM for strategy identification.

    \b
    Example:
      tasty-subscription positions-summary
      tasty-subscription positions-summary | claude --print "identify the strategy for each underlying"
    """

    async def _run() -> None:
        from tastytrade.analytics.positions import PositionMetricsReader

        reader = PositionMetricsReader()
        try:
            await reader.read()
            summary = reader.summary
            if summary.empty:
                click.echo("No positions found in Redis. Is account-stream running?")
                return
            click.echo(summary.astype(object).fillna("").to_string(index=False))
        finally:
            await reader.close()

    asyncio.run(_run())


@cli.command(name="strategies")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output in JSON format for machine consumption.",
)
def strategies_cmd(as_json: bool) -> None:
    """Classify positions into named option strategies.

    Uses deterministic pattern matching to identify strategies like
    iron condors, strangles, jade lizards, covered calls, etc.
    Includes health monitoring alerts.

    \b
    Example:
      tasty-subscription strategies
      tasty-subscription strategies --json
    """

    async def _run() -> None:
        from tastytrade.analytics.positions import PositionMetricsReader

        reader = PositionMetricsReader()
        try:
            await reader.read()
            summary = reader.strategy_summary
            if summary.empty:
                click.echo("No positions found in Redis. Is account-stream running?")
                return
            if as_json:
                click.echo(summary.to_json(orient="records", indent=2))
            else:
                click.echo(summary.astype(object).fillna("").to_string(index=False))
        finally:
            await reader.close()

    asyncio.run(_run())


def format_campaign_detail(chains: list[dict[str, object]]) -> None:
    """Print human-readable detail of chain roll history."""
    for chain_data in chains:
        click.echo(f"{'=' * 70}")
        click.echo(f"Chain: {chain_data['chain_id']}  {chain_data['description']}")
        click.echo(
            f"Underlying: {chain_data['underlying']}  "
            f"Status: {chain_data['status']}  "
            f"Rolls: {chain_data['rolls']}"
        )
        click.echo(
            f"Realized P&L: {chain_data['realized_pnl']}  "
            f"Fees: {chain_data['total_fees']}  "
            f"P&L Open: {chain_data['pnl_open']}"
        )
        click.echo(f"Net P&L: {chain_data['net_pnl']}")
        click.echo(f"Opened: {chain_data.get('opened_at', '-')}")

        nodes = chain_data.get("nodes")
        if isinstance(nodes, list):
            click.echo(f"\n  {'Roll History':}")
            click.echo(f"  {'-' * 60}")
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                roll_marker = " [ROLL]" if node.get("roll") else ""
                click.echo(
                    f"  {node.get('occurred_at', '-')}  "
                    f"{node.get('description', '-')}{roll_marker}"
                )
                click.echo(
                    f"    Fill cost: {node.get('fill_cost', '-')}  "
                    f"Fees: {node.get('total_fees', '-')}"
                )
                legs = node.get("legs")
                if isinstance(legs, list):
                    for leg in legs:
                        if isinstance(leg, dict):
                            click.echo(
                                f"      {leg.get('action', '-')} "
                                f"{leg.get('fill_quantity', '-')}x "
                                f"{leg.get('symbol', '-')}"
                            )
                entries = node.get("entries")
                if isinstance(entries, list) and entries:
                    for entry in entries:
                        if isinstance(entry, dict):
                            click.echo(
                                f"      => {entry.get('direction', '-')} "
                                f"{entry.get('quantity', '-')}x "
                                f"{entry.get('symbol', '-')}"
                            )
                snapshot = node.get("market_snapshot")
                if isinstance(snapshot, dict):
                    click.echo(
                        f"    Market: delta={snapshot.get('total_delta', '-')} "
                        f"theta={snapshot.get('total_theta', '-')}"
                    )

        open_legs = chain_data.get("open_legs")
        if isinstance(open_legs, list) and open_legs:
            click.echo(f"\n  {'Open Legs':}")
            click.echo(f"  {'-' * 60}")
            for leg in open_legs:
                if isinstance(leg, dict):
                    pnl = leg.get("pnl_open")
                    mark_str = f"  P&L=${pnl:,.2f}" if pnl is not None else ""
                    click.echo(
                        f"    {leg.get('direction', '-')} "
                        f"{leg.get('quantity', '-')}x "
                        f"{leg.get('symbol', '-')}{mark_str}"
                    )
        click.echo()


@cli.command(name="chains")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output in JSON format for machine consumption.",
)
@click.option(
    "--campaign",
    is_flag=True,
    default=False,
    help="Group by underlying with campaign P&L aggregation.",
)
@click.option(
    "--underlying",
    default=None,
    help="Filter to specific underlying (e.g., /ZB, /ES, SPY).",
)
@click.option(
    "--detail",
    is_flag=True,
    default=False,
    help="Show full roll history per chain with node-level fills.",
)
def chains_cmd(
    as_json: bool,
    campaign: bool,
    underlying: str | None,
    detail: bool,
) -> None:
    """Show trade chain lifecycle summary from Redis.

    Displays one row per OrderChain with strategy name, rolls,
    realized P&L, fees, and open legs. Requires account-stream
    to be running.

    \b
    Modes:
      (default)     One row per chain
      --campaign    Aggregate by underlying with campaign P&L
      --detail      Full roll history per chain with node-level fills

    \b
    Examples:
      tasty-subscription chains
      tasty-subscription chains --campaign
      tasty-subscription chains --campaign --underlying /ZB
      tasty-subscription chains --detail --underlying /ZB
      tasty-subscription chains --json
    """

    async def _run() -> None:
        import json as json_mod

        from tastytrade.analytics.positions import PositionMetricsReader

        reader = PositionMetricsReader()
        try:
            await reader.read()

            if detail:
                data = reader.campaign_detail(underlying=underlying)
                if not data:
                    click.echo("No matching chains found.")
                    return
                if as_json:
                    click.echo(json_mod.dumps(data, indent=2, default=str))
                else:
                    format_campaign_detail(data)
            elif campaign:
                df = reader.campaign_summary
                if df.empty:
                    click.echo(
                        "No trade chains found in Redis. Is account-stream running?"
                    )
                    return
                if underlying:
                    df = df[df["underlying"] == underlying]
                    if df.empty:
                        click.echo(f"No chains found for underlying: {underlying}")
                        return
                if as_json:
                    click.echo(df.to_json(orient="records", indent=2))
                else:
                    click.echo(df.astype(object).fillna("").to_string(index=False))
            else:
                df = reader.chain_summary
                if df.empty:
                    click.echo(
                        "No trade chains found in Redis. Is account-stream running?"
                    )
                    return
                if underlying:
                    df = df[df["underlying"] == underlying]
                    if df.empty:
                        click.echo(f"No chains found for underlying: {underlying}")
                        return
                if as_json:
                    click.echo(df.to_json(orient="records", indent=2))
                else:
                    click.echo(df.astype(object).fillna("").to_string(index=False))
        finally:
            await reader.close()

    asyncio.run(_run())


@cli.command(name="options")
@click.option(
    "--symbol",
    required=True,
    help="Underlying symbol (e.g., SPX, CSCO, /GC, /ES).",
)
@click.option(
    "--dte",
    default=None,
    help="Comma-separated target DTEs (e.g., 0,30,45). Returns closest match for each.",
)
@click.option(
    "--strikes",
    is_flag=True,
    default=False,
    help="Show full strike-level detail instead of expiration summary.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output in JSON format for machine consumption.",
)
def options_cmd(symbol: str, dte: str | None, strikes: bool, as_json: bool) -> None:
    """Fetch option chain snapshot for any underlying.

    Supports equities (SPX, CSCO, XLE), ETFs (SPY, QQQ), and
    futures (/GC, /ES, /CL). Auto-detects instrument type by
    symbol prefix.

    \b
    Examples:
      tasty-subscription options --symbol SPX
      tasty-subscription options --symbol /GC --dte 0,30,45
      tasty-subscription options --symbol CSCO --dte 30 --strikes
    """
    target_dtes: list[int] | None = None
    if dte:
        try:
            target_dtes = [int(d.strip()) for d in dte.split(",")]
        except ValueError:
            raise click.BadParameter(
                f"Invalid DTE values: '{dte}'. Expected comma-separated integers."
            ) from None

    async def _run() -> None:
        from tastytrade.config.manager import RedisConfigManager
        from tastytrade.connections import Credentials
        from tastytrade.connections.auth import create_auth_strategy
        from tastytrade.connections.requests import AsyncSessionHandler
        from tastytrade.market.option_chains import get_option_chain

        config = RedisConfigManager()
        credentials = Credentials(config=config, env="Live")
        auth_strategy = create_auth_strategy(credentials)
        session = AsyncSessionHandler(credentials, auth_strategy)
        await session.create_session()

        try:
            df = await get_option_chain(session, symbol, target_dtes)

            if df.is_empty():
                click.echo(f"No option chain data found for {symbol}.")
                return

            if as_json:
                click.echo(df.write_json())
            else:
                # Summary header
                n_expirations = df["expiration"].n_unique()
                n_strikes = df["strike"].n_unique()
                roots = df["root"].unique().sort().to_list()
                click.echo(
                    f"{symbol}: {df.shape[0]} options, "
                    f"{n_expirations} expirations, "
                    f"{n_strikes} strikes, "
                    f"roots={roots}"
                )
                if target_dtes:
                    matched = sorted(df["dte"].unique().to_list())
                    click.echo(
                        f"DTE filter: requested={target_dtes}, matched={matched}"
                    )
                click.echo()

                if strikes:
                    # Show full strike-level detail (no truncation)
                    display_cols = [
                        "root",
                        "expiration",
                        "dte",
                        "strike",
                        "option_type",
                        "symbol",
                        "streamer_symbol",
                    ]
                    available = [c for c in display_cols if c in df.columns]
                    with pl.Config(tbl_rows=-1):
                        click.echo(
                            df.select(available).sort(
                                "root", "expiration", "strike", "option_type"
                            )
                        )
                else:
                    # Show expiration summary
                    summary = (
                        df.group_by(
                            "root",
                            "expiration",
                            "dte",
                            "expiration_type",
                            "settlement",
                        )
                        .agg(pl.col("strike").n_unique().alias("strikes"))
                        .sort("dte", "root")
                    )
                    click.echo(summary)
        finally:
            await session.close()

    import polars as pl

    asyncio.run(_run())


def main() -> None:
    """Entry point for the tasty-subscription CLI."""
    cli()


if __name__ == "__main__":
    main()
