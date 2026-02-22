"""Functional test script for the backtesting framework.

Runs a backtest against production InfluxDB data for SPX and NVDA,
verifying the full pipeline: InfluxDB → Redis replay → Engine → BacktestSignal → InfluxDB.

Usage:
    uv run python src/devtools/backtest_functional_test.py

Prerequisites:
    - Redis running (localhost:6379 or REDIS_HOST/REDIS_PORT env vars)
    - InfluxDB accessible with credentials in Redis config or .env
"""

import asyncio
import logging
import sys
from datetime import date

from tastytrade.backtest.cli import run_backtest_orchestrated
from tastytrade.backtest.models import BacktestConfig, resolve_pricing_interval
from tastytrade.common.logging import setup_logging

setup_logging(level=logging.INFO, console=True, file=False)
logger = logging.getLogger(__name__)


def test_pricing_interval_resolution() -> None:
    """Verify pricing interval auto-selection (DXLink format)."""
    cases = [
        ("5m", None, "m"),
        ("1d", None, "h"),
        ("1h", None, "15m"),
        ("15m", None, "5m"),
        ("1m", None, "m"),
        ("5m", "1m", "m"),  # explicit override, normalized to DXLink
        ("1d", "5m", "5m"),  # explicit override, already DXLink
    ]
    for signal, pricing, expected in cases:
        result = resolve_pricing_interval(signal, pricing)
        status = "PASS" if result == expected else "FAIL"
        logger.info(
            "[%s] resolve_pricing_interval(%s, %s) = %s (expected %s)",
            status,
            signal,
            pricing,
            result,
            expected,
        )
        assert result == expected, f"Expected {expected}, got {result}"

    logger.info("All pricing interval resolution tests passed")


def test_config_creation() -> None:
    """Verify BacktestConfig creation and properties."""
    config = BacktestConfig(
        symbol="SPX",
        signal_interval="5m",
        start_date=date(2025, 1, 6),
        end_date=date(2025, 1, 10),
    )
    assert config.signal_symbol == "SPX{=5m}"
    assert config.pricing_symbol == "SPX{=m}"
    assert config.resolved_pricing_interval == "m"
    assert config.engine_type == "hull_macd"
    assert config.source == "backtest"
    assert len(config.backtest_id) > 0

    logger.info("BacktestConfig creation test passed")
    logger.info("  backtest_id: %s", config.backtest_id)
    logger.info("  signal_symbol: %s", config.signal_symbol)
    logger.info("  pricing_symbol: %s", config.pricing_symbol)


def test_backtest_signal_model() -> None:
    """Verify BacktestSignal model properties."""
    from datetime import datetime

    from tastytrade.backtest.models import BacktestSignal

    signal = BacktestSignal(
        eventSymbol="SPX{=5m}",
        start_time=datetime(2025, 1, 6, 10, 30),
        label="OPEN BULLISH",
        signal_type="OPEN",
        direction="BULLISH",
        engine="hull_macd",
        hull_direction="Up",
        hull_value=5950.0,
        macd_value=1.5,
        macd_signal=0.8,
        macd_histogram=0.7,
        close_price=5945.0,
        trigger="confluence",
        backtest_id="test-123",
        source="backtest",
        entry_price=5944.5,
        signal_interval="5m",
        pricing_interval="1m",
    )

    assert signal.event_type == "backtest_signal"
    assert signal.__class__.__name__ == "BacktestSignal"
    assert signal.backtest_id == "test-123"
    assert signal.source == "backtest"
    assert signal.entry_price == 5944.5
    assert signal.signal_interval == "5m"
    assert signal.pricing_interval == "1m"

    # Verify JSON roundtrip
    json_str = signal.model_dump_json()
    assert "backtest_signal" in json_str
    assert "backtest_id" in json_str

    logger.info("BacktestSignal model test passed")
    logger.info("  class_name: %s", signal.__class__.__name__)
    logger.info("  event_type: %s", signal.event_type)


async def test_backtest_spx(start: date, end: date) -> None:
    """Run a full backtest for SPX."""
    config = BacktestConfig(
        symbol="SPX",
        signal_interval="5m",
        start_date=start,
        end_date=end,
    )
    logger.info("Running SPX backtest: %s to %s", start, end)
    await run_backtest_orchestrated(config)


async def test_backtest_nvda(start: date, end: date) -> None:
    """Run a full backtest for NVDA."""
    config = BacktestConfig(
        symbol="NVDA",
        signal_interval="5m",
        start_date=start,
        end_date=end,
    )
    logger.info("Running NVDA backtest: %s to %s", start, end)
    await run_backtest_orchestrated(config)


def main() -> None:
    logger.info("=" * 60)
    logger.info("BACKTEST FRAMEWORK FUNCTIONAL TEST")
    logger.info("=" * 60)

    # Unit-level checks first
    test_pricing_interval_resolution()
    test_config_creation()
    test_backtest_signal_model()

    # Integration test with production data
    # Use a 1-week window where 1-minute data is available for both symbols
    # SPX{=m} starts 2025-01-24, NVDA{=m} starts 2025-02-11
    start = date(2025, 2, 18)
    end = date(2025, 2, 21)

    logger.info("=" * 60)
    logger.info("INTEGRATION TEST — SPX backtest (%s to %s)", start, end)
    logger.info("=" * 60)

    try:
        asyncio.run(test_backtest_spx(start, end))
        logger.info("SPX backtest: PASS")
    except Exception as e:
        logger.error("SPX backtest: FAIL — %s", e)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("INTEGRATION TEST — NVDA backtest (%s to %s)", start, end)
    logger.info("=" * 60)

    try:
        asyncio.run(test_backtest_nvda(start, end))
        logger.info("NVDA backtest: PASS")
    except Exception as e:
        logger.error("NVDA backtest: FAIL — %s", e)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("ALL FUNCTIONAL TESTS PASSED")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
