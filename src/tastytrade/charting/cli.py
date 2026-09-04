"""CLI entry point for tasty-chart.

Thin wrapper over ChartServer — parses args and starts the server.
"""

import asyncio
import logging
import os
import socket
from pathlib import Path

import click
import uvicorn

from tastytrade.common.logging import setup_logging


def lan_ip() -> str:
    """Best-effort LAN IP for the printed URL (no traffic is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "localhost"


@click.command()
@click.option("--symbol", default="SPX", help="Market symbol (e.g., SPX, AAPL, /ESM5)")
@click.option("--interval", default="m", help="Candle interval (m, 5m, 15m, 1h)")
@click.option("--port", default=8080, type=int, help="Server port")
@click.option(
    "--reload",
    is_flag=True,
    help="Restart automatically when Python under src/tastytrade changes",
)
@click.option("--debug", is_flag=True, help="Enable debug logging")
def main(
    symbol: str,
    interval: str,
    port: int,
    reload: bool,
    debug: bool,
) -> None:
    """Start a live chart server for a market symbol."""
    setup_logging(level=logging.DEBUG if debug else logging.INFO)
    logger = logging.getLogger(__name__)

    from tastytrade.charting.server import ChartServer

    host = lan_ip()
    url = f"http://{host}:{port}/?symbol={symbol}&interval={interval}"
    logger.info("Starting tasty-chart: %s %s on port %d", symbol, interval, port)
    click.echo(f"\n  tasty-chart → {url}\n")

    if reload:
        # Uvicorn's reloader needs an import string and a fresh worker process;
        # hand the arguments over through the environment (see create_app).
        os.environ["TASTY_CHART_SYMBOL"] = symbol
        os.environ["TASTY_CHART_INTERVAL"] = interval
        os.environ["TASTY_CHART_HOST"] = host
        os.environ["TASTY_CHART_PORT"] = str(port)
        if debug:
            os.environ["TASTY_CHART_DEBUG"] = "1"
        uvicorn.run(
            "tastytrade.charting.server:create_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
            reload_dirs=[str(Path(__file__).resolve().parents[1])],
            log_level="debug" if debug else "info",
        )
        return

    server = ChartServer(
        symbol=symbol,
        interval=interval,
        host=host,
        port=port,
    )
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
