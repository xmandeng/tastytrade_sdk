"""Tests for PositionMetricsReader -- pure Redis consumer."""

import json
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from tastytrade.analytics.positions import PositionMetricsReader


def make_position_json(
    symbol: str,
    streamer: str,
    qty: str = "100.0",
    direction: str = "Long",
    inst_type: str = "Equity",
) -> str:
    return json.dumps(
        {
            "account-number": "5WT00001",
            "symbol": symbol,
            "instrument-type": inst_type,
            "quantity": qty,
            "quantity-direction": direction,
            "streamer-symbol": streamer,
        }
    )


def make_quote_json(symbol: str, bid: float, ask: float) -> str:
    return json.dumps(
        {
            "eventSymbol": symbol,
            "bidPrice": bid,
            "askPrice": ask,
            "bidSize": 100.0,
            "askSize": 200.0,
        }
    )


def make_greeks_json(symbol: str, delta: float, iv: float) -> str:
    return json.dumps(
        {
            "eventSymbol": symbol,
            "delta": delta,
            "gamma": 0.01,
            "theta": -0.05,
            "vega": 0.10,
            "rho": -0.02,
            "volatility": iv,
        }
    )


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def reader(mock_redis: AsyncMock) -> PositionMetricsReader:
    r = PositionMetricsReader.__new__(PositionMetricsReader)
    r.redis = mock_redis
    r.position_metrics_df = pd.DataFrame()
    r.tracker = None
    r.instruments = {}
    return r


@pytest.mark.asyncio
async def test_read_returns_dataframe(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    mock_redis.hgetall.side_effect = [
        {b"SPY": make_position_json("SPY", "SPY").encode()},  # positions
        {b"SPY": make_quote_json("SPY", 690.0, 691.0).encode()},  # quotes
        {},  # greeks
        {},  # instruments
    ]
    df = await reader.read()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["mid_price"] == 690.5


@pytest.mark.asyncio
async def test_read_joins_greeks_for_options(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    mock_redis.hgetall.side_effect = [
        {
            b".SPY260402P666": make_position_json(
                "SPY P666", ".SPY260402P666", inst_type="Equity Option"
            ).encode()
        },
        {b".SPY260402P666": make_quote_json(".SPY260402P666", 5.75, 5.80).encode()},
        {b".SPY260402P666": make_greeks_json(".SPY260402P666", -0.24, 0.19).encode()},
        {},  # instruments
    ]
    df = await reader.read()
    assert len(df) == 1
    assert df.iloc[0]["delta"] == -0.24
    assert df.iloc[0]["implied_volatility"] == 0.19


@pytest.mark.asyncio
async def test_read_empty_positions_returns_empty_df(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    mock_redis.hgetall.side_effect = [{}, {}, {}, {}]
    df = await reader.read()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


@pytest.mark.asyncio
async def test_read_includes_required_columns(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    mock_redis.hgetall.side_effect = [
        {b"SPY": make_position_json("SPY", "SPY").encode()},
        {b"SPY": make_quote_json("SPY", 690.0, 691.0).encode()},
        {},  # greeks
        {},  # instruments
    ]
    df = await reader.read()
    for col in [
        "symbol",
        "quantity",
        "quantity_direction",
        "mid_price",
        "delta",
        "implied_volatility",
    ]:
        assert col in df.columns, f"Missing column: {col}"
