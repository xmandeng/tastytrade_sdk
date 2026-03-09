"""Tests for PositionMetricsReader -- pure Redis consumer."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from tastytrade.accounts.models import InstrumentType, TradeChain
from tastytrade.analytics.positions import PositionMetricsReader, underlyings_match
from tastytrade.analytics.strategies.models import ParsedLeg, Strategy, StrategyType


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
# TradeChain enrichment (experimental — TT-80)
# ---------------------------------------------------------------------------


def make_trade_chain(
    chain_id: str = "12345",
    underlying: str = "/6E",
    description: str = "Strangle w/ a roll",
    is_open: bool = True,
    roll_count: int = 1,
    realized_gain_with_fees: str = "7.68",
    total_fees: str = "7.68",
    open_entry_symbols: list[str] | None = None,
) -> TradeChain:
    """Build a minimal TradeChain for testing."""
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
    return TradeChain.model_validate(
        {
            "id": chain_id,
            "description": description,
            "underlying-symbol": underlying,
            "computed-data": {
                "open": is_open,
                "roll-count": roll_count,
                "realized-gain-with-fees": realized_gain_with_fees,
                "total-fees": total_fees,
                "open-entries": entries,
            },
            "lite-nodes": [],
        }
    )


def make_strategy(
    underlying: str = "/6E",
    leg_symbols: list[str] | None = None,
) -> Strategy:
    """Build a minimal Strategy for testing chain matching."""
    symbols = leg_symbols or ["./6EM6 EUUJ6 260403C1.18", "./6EM6 EUUJ6 260403P1.13"]
    legs = tuple(
        ParsedLeg(
            streamer_symbol=sym,
            symbol=sym,
            underlying=underlying,
            instrument_type=InstrumentType.FUTURE_OPTION,
            signed_quantity=-1.0,
            option_type="C",
            strike=Decimal("1.18"),
        )
        for sym in symbols
    )
    return Strategy(
        strategy_type=StrategyType.SHORT_STRANGLE,
        underlying=underlying,
        legs=legs,
    )


class TestMatchTradeChain:
    def test_matches_by_underlying_and_open_entries(
        self, reader: PositionMetricsReader
    ) -> None:
        chain = make_trade_chain(
            open_entry_symbols=[
                "./6EM6 EUUJ6 260403C1.18",
                "./6EM6 EUUJ6 260403P1.13",
            ],
        )
        reader.trade_chains = {chain.id: chain}
        strat = make_strategy()
        match = reader.match_trade_chain(strat)
        assert match is not None
        assert match.id == "12345"
        assert match.computed_data.roll_count == 1

    def test_no_match_wrong_underlying(self, reader: PositionMetricsReader) -> None:
        chain = make_trade_chain(underlying="SPY")
        reader.trade_chains = {chain.id: chain}
        strat = make_strategy(underlying="/6E")
        assert reader.match_trade_chain(strat) is None

    def test_no_match_when_chain_closed(self, reader: PositionMetricsReader) -> None:
        chain = make_trade_chain(is_open=False)
        reader.trade_chains = {chain.id: chain}
        strat = make_strategy()
        assert reader.match_trade_chain(strat) is None

    def test_no_match_empty_chains(self, reader: PositionMetricsReader) -> None:
        reader.trade_chains = {}
        strat = make_strategy()
        assert reader.match_trade_chain(strat) is None

    def test_best_overlap_wins(self, reader: PositionMetricsReader) -> None:
        """When multiple chains match, pick the one with most leg overlap."""
        partial = make_trade_chain(
            chain_id="partial",
            open_entry_symbols=["./6EM6 EUUJ6 260403C1.18"],
        )
        full = make_trade_chain(
            chain_id="full",
            open_entry_symbols=[
                "./6EM6 EUUJ6 260403C1.18",
                "./6EM6 EUUJ6 260403P1.13",
            ],
        )
        reader.trade_chains = {partial.id: partial, full.id: full}
        strat = make_strategy()
        match = reader.match_trade_chain(strat)
        assert match is not None
        assert match.id == "full"

    def test_futures_prefix_match(self, reader: PositionMetricsReader) -> None:
        """Chain underlying '/6E' matches strategy underlying '/6EM6'."""
        chain = make_trade_chain(
            underlying="/6E",
            open_entry_symbols=[
                "./6EM6 EUUJ6 260403C1.18",
                "./6EM6 EUUJ6 260403P1.13",
            ],
        )
        reader.trade_chains = {chain.id: chain}
        strat = make_strategy(underlying="/6EM6")
        match = reader.match_trade_chain(strat)
        assert match is not None
        assert match.id == "12345"


class TestUnderlyingsMatch:
    def test_exact_match(self) -> None:
        assert underlyings_match("SPY", "SPY") is True

    def test_futures_root_to_contract(self) -> None:
        assert underlyings_match("/6E", "/6EM6") is True

    def test_futures_contract_to_root(self) -> None:
        assert underlyings_match("/6EM6", "/6E") is True

    def test_no_match(self) -> None:
        assert underlyings_match("/ES", "/6E") is False

    def test_equity_no_false_positive(self) -> None:
        assert underlyings_match("SPY", "SPYG") is False
