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


def make_trade_chain_json(
    chain_id: str = "12345",
    underlying: str = "/6E",
    description: str = "Strangle w/ a roll",
    is_open: bool = True,
    roll_count: int = 1,
    realized_gain_with_fees: str = "7.68",
    total_fees: str = "7.68",
    opened_at: str = "2026-03-07T15:30:00.000+0000",
    open_entry_symbols: list[str] | None = None,
) -> str:
    """Build a trade chain JSON payload for Redis mock."""
    entries = []
    for sym in open_entry_symbols or []:
        entries.append(
            {
                "symbol": sym,
                "instrument-type": "Future Option",
                "quantity": "1",
                "quantity-type": "Short",
                "quantity-numeric": "-1",
            }
        )
    return json.dumps(
        {
            "id": chain_id,
            "description": description,
            "underlying-symbol": underlying,
            "computed-data": {
                "open": is_open,
                "roll-count": roll_count,
                "realized-gain-with-fees": realized_gain_with_fees,
                "total-fees": total_fees,
                "opened-at": opened_at,
                "open-entries": entries,
            },
            "lite-nodes": [],
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
    r.entry_credit_records = {}
    r.entry_credits = {}
    r.trade_chains = {}
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
        {},  # entry credits
        {},  # trade chains
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
        {},  # entry credits
        {},  # trade chains
    ]
    df = await reader.read()
    assert len(df) == 1
    assert df.iloc[0]["delta"] == -0.24
    assert df.iloc[0]["implied_volatility"] == 0.19


@pytest.mark.asyncio
async def test_read_empty_positions_returns_empty_df(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    mock_redis.hgetall.side_effect = [{}, {}, {}, {}, {}, {}]
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
        {},  # entry credits
        {},  # trade chains
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


# ---------------------------------------------------------------------------
# TradeChain position-level enrichment (experimental — TT-80)
# ---------------------------------------------------------------------------

CALL_SYMBOL = "./6EM6 EUUJ6 260403C1.18"
PUT_SYMBOL = "./6EM6 EUUJ6 260403P1.13"


@pytest.mark.asyncio
async def test_trade_chain_enriches_positions(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    """Positions matching chain open-entries get lifecycle columns."""
    mock_redis.hgetall.side_effect = [
        {  # positions
            b"call": make_position_json(
                CALL_SYMBOL,
                CALL_SYMBOL,
                qty="1.0",
                direction="Short",
                inst_type="Future Option",
            ).encode(),
            b"put": make_position_json(
                PUT_SYMBOL,
                PUT_SYMBOL,
                qty="1.0",
                direction="Short",
                inst_type="Future Option",
            ).encode(),
        },
        {},  # quotes
        {},  # greeks
        {},  # instruments
        {},  # entry credits
        {  # trade chains
            b"12345": make_trade_chain_json(
                open_entry_symbols=[CALL_SYMBOL, PUT_SYMBOL],
            ).encode(),
        },
    ]
    df = await reader.read()
    assert len(df) == 2

    # Both positions should have chain data
    for _, row in df.iterrows():
        assert row["chain_id"] == "12345"
        assert row["tt_strategy"] == "Strangle w/ a roll"
        assert row["rolls"] == 1
        assert row["realized_pnl"] == "7.68"
        assert row["chain_fees"] == "7.68"
        assert row["opened_at"] == "2026-03-07T15:30:00.000+0000"


@pytest.mark.asyncio
async def test_no_chain_data_when_no_match(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    """Positions with no matching chain get None for lifecycle columns."""
    mock_redis.hgetall.side_effect = [
        {b"SPY": make_position_json("SPY", "SPY").encode()},
        {},  # quotes
        {},  # greeks
        {},  # instruments
        {},  # entry credits
        {  # trade chain for different symbols
            b"99999": make_trade_chain_json(
                open_entry_symbols=[CALL_SYMBOL],
            ).encode(),
        },
    ]
    df = await reader.read()
    assert len(df) == 1
    assert pd.isna(df.iloc[0].get("chain_id")) or df.iloc[0].get("chain_id") is None


@pytest.mark.asyncio
async def test_closed_chain_does_not_enrich(
    reader: PositionMetricsReader, mock_redis: AsyncMock
) -> None:
    """Closed chains are not mapped to positions."""
    mock_redis.hgetall.side_effect = [
        {
            b"call": make_position_json(
                CALL_SYMBOL,
                CALL_SYMBOL,
                qty="1.0",
                direction="Short",
                inst_type="Future Option",
            ).encode(),
        },
        {},  # quotes
        {},  # greeks
        {},  # instruments
        {},  # entry credits
        {  # closed chain
            b"12345": make_trade_chain_json(
                is_open=False,
                open_entry_symbols=[CALL_SYMBOL],
            ).encode(),
        },
    ]
    df = await reader.read()
    assert len(df) == 1
    # No enrichment columns when chain is closed (no symbol lookup built)
    assert "chain_id" not in df.columns or pd.isna(df.iloc[0].get("chain_id"))
