"""Tests for PositionMetricsReader -- pure Redis consumer."""

import json
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from tastytrade.accounts.models import TradeChain
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


CALL_SYMBOL = "./6EM6 EUUJ6 260403C1.18"
PUT_SYMBOL = "./6EM6 EUUJ6 260403P1.13"


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


# ---------------------------------------------------------------------------
# Core reader tests
# ---------------------------------------------------------------------------


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
# chain_summary (experimental — TT-80)
# ---------------------------------------------------------------------------


class TestChainSummary:
    def test_empty_when_no_chains(self, reader: PositionMetricsReader) -> None:
        reader.trade_chains = {}
        df = reader.chain_summary
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "chain_id" in df.columns

    def test_open_chain_produces_row(self, reader: PositionMetricsReader) -> None:
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                open_entry_symbols=[CALL_SYMBOL, PUT_SYMBOL],
            )
        )
        reader.trade_chains = {chain.id: chain}
        df = reader.chain_summary
        assert len(df) == 1
        row = df.iloc[0]
        assert row["chain_id"] == "12345"
        assert row["underlying"] == "/6E"
        assert row["tt_strategy"] == "Strangle w/ a roll"
        assert row["status"] == "open"
        assert row["rolls"] == 1
        assert row["realized_pnl"] == "7.68"
        assert row["total_fees"] == "7.68"
        assert CALL_SYMBOL in row["legs"]
        assert PUT_SYMBOL in row["legs"]

    def test_closed_chain_shows_closed_status(
        self, reader: PositionMetricsReader
    ) -> None:
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                chain_id="99999",
                description="Vertical",
                is_open=False,
                roll_count=0,
                realized_gain_with_fees="150.0",
            )
        )
        reader.trade_chains = {chain.id: chain}
        df = reader.chain_summary
        assert len(df) == 1
        assert df.iloc[0]["status"] == "closed"
        assert df.iloc[0]["realized_pnl"] == "150.0"

    def test_multiple_chains(self, reader: PositionMetricsReader) -> None:
        chain_a = TradeChain.model_validate_json(
            make_trade_chain_json(
                chain_id="aaa",
                description="Strangle",
                open_entry_symbols=[CALL_SYMBOL],
            )
        )
        chain_b = TradeChain.model_validate_json(
            make_trade_chain_json(
                chain_id="bbb",
                description="Iron Condor",
                underlying="RUT",
                open_entry_symbols=[PUT_SYMBOL],
            )
        )
        reader.trade_chains = {chain_a.id: chain_a, chain_b.id: chain_b}
        df = reader.chain_summary
        assert len(df) == 2
        assert set(df["chain_id"]) == {"aaa", "bbb"}

    @pytest.mark.asyncio
    async def test_read_populates_trade_chains(
        self, reader: PositionMetricsReader, mock_redis: AsyncMock
    ) -> None:
        """read() loads trade chains so chain_summary works after."""
        mock_redis.hgetall.side_effect = [
            {b"SPY": make_position_json("SPY", "SPY").encode()},
            {},  # quotes
            {},  # greeks
            {},  # instruments
            {},  # entry credits
            {  # trade chains
                b"12345": make_trade_chain_json(
                    open_entry_symbols=[CALL_SYMBOL],
                ).encode(),
            },
        ]
        await reader.read()
        df = reader.chain_summary
        assert len(df) == 1
        assert df.iloc[0]["chain_id"] == "12345"
