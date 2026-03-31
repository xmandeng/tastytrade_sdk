"""CLI entry point for tasty-chart.

Thin wrapper over ChartServer — parses args and starts the server.
"""

import asyncio
import logging

import click

from tastytrade.common.logging import setup_logging


@click.command()
@click.option("--symbol", default="SPX", help="Market symbol (e.g., SPX, AAPL, /ESM5)")
@click.option("--interval", default="m", help="Candle interval (m, 5m, 15m, 1h)")
@click.option("--port", default=8080, type=int, help="Server port")
@click.option("--debug", is_flag=True, help="Enable debug logging")
def main(
    symbol: str,
    interval: str,
    port: int,
    debug: bool,
) -> None:
    """Start a live chart server for a market symbol."""
    setup_logging(level=logging.DEBUG if debug else logging.INFO)
    logger = logging.getLogger(__name__)

    from tastytrade.charting.server import ChartServer

    url = f"http://localhost:{port}/?symbol={symbol}&interval={interval}"
    logger.info("Starting tasty-chart: %s %s on port %d", symbol, interval, port)
    click.echo(f"\n  tasty-chart → {url}\n")

    server = ChartServer(
        symbol=symbol,
        interval=interval,
        port=port,
    )
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
