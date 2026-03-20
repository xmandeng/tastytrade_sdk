"""Tests for PositionMetricsReader -- pure Redis consumer."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from tastytrade.accounts.models import QuantityDirection, TradeChain
from tastytrade.analytics.positions import PositionMetricsReader, apply_effect


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
    total_fees_effect: str = "Debit",
    realized_gain: str | None = None,
    realized_gain_effect: str | None = None,
    opened_at: str = "2026-03-07T15:30:00.000+0000",
    open_entry_symbols: list[str] | None = None,
    open_entry_directions: list[str] | None = None,
    lite_nodes: list[dict[str, object]] | None = None,
) -> str:
    """Build a trade chain JSON payload for Redis mock."""
    directions = open_entry_directions or []
    entries = []
    for i, sym in enumerate(open_entry_symbols or []):
        direction = directions[i] if i < len(directions) else "Short"
        sign = "-1" if direction == "Short" else "1"
        entries.append(
            {
                "symbol": sym,
                "instrument-type": "Future Option",
                "quantity": "1",
                "quantity-type": direction,
                "quantity-numeric": sign,
            }
        )
    computed: dict[str, object] = {
        "open": is_open,
        "roll-count": roll_count,
        "realized-gain-with-fees": realized_gain_with_fees,
        "total-fees": total_fees,
        "total-fees-effect": total_fees_effect,
        "opened-at": opened_at,
        "open-entries": entries,
    }
    if realized_gain is not None:
        computed["realized-gain"] = realized_gain
    if realized_gain_effect is not None:
        computed["realized-gain-effect"] = realized_gain_effect
    return json.dumps(
        {
            "id": chain_id,
            "description": description,
            "underlying-symbol": underlying,
            "computed-data": computed,
            "lite-nodes": lite_nodes or [],
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


# ---------------------------------------------------------------------------
# apply_effect utility (TT-91)
# ---------------------------------------------------------------------------


class TestApplyEffect:
    def test_credit_is_positive(self) -> None:
        assert apply_effect("100.50", "Credit") == Decimal("100.50")

    def test_debit_is_negative(self) -> None:
        assert apply_effect("75.00", "Debit") == Decimal("-75.00")

    def test_none_amount_returns_zero(self) -> None:
        assert apply_effect(None, "Credit") == Decimal("0")

    def test_none_effect_treated_as_positive(self) -> None:
        assert apply_effect("50.0", None) == Decimal("50.0")

    def test_zero_amount(self) -> None:
        assert apply_effect("0.0", "Debit") == Decimal("0.0")


# ---------------------------------------------------------------------------
# campaign_summary (TT-91) — chain-based P&L with corrected unrealized
# ---------------------------------------------------------------------------


def make_position_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Build a minimal position DataFrame for campaign tests."""
    defaults = {
        "symbol": "",
        "mid_price": None,
        "average_open_price": None,
        "quantity": 1.0,
        "multiplier": 1.0,
        "quantity_direction": QuantityDirection.SHORT,
    }
    full_rows = [{**defaults, **r} for r in rows]
    return pd.DataFrame(full_rows)


class TestCampaignSummary:
    def test_empty_when_no_chains(self, reader: PositionMetricsReader) -> None:
        reader.trade_chains = {}
        df = reader.campaign_summary
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "underlying" in df.columns
        assert "net_pnl" in df.columns

    def test_closed_chain_realized_only(self, reader: PositionMetricsReader) -> None:
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="200.0",
                realized_gain_effect="Credit",
                total_fees="10.0",
                roll_count=2,
                is_open=False,
            )
        )
        reader.trade_chains = {chain.id: chain}
        df = reader.campaign_summary
        assert len(df) == 1
        row = df.iloc[0]
        assert row["underlying"] == "/6E"
        assert row["realized_pnl"] == 200.0
        assert row["pnl_open"] == 0.0
        assert row["net_pnl"] == 200.0
        assert row["recovery_needed"] == 0.0

    def test_debit_effect_makes_realized_negative(
        self, reader: PositionMetricsReader
    ) -> None:
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="450.0",
                realized_gain_effect="Debit",
                total_fees="12.0",
                is_open=False,
            )
        )
        reader.trade_chains = {chain.id: chain}
        df = reader.campaign_summary
        row = df.iloc[0]
        assert row["realized_pnl"] == -450.0
        assert row["net_pnl"] == -450.0
        assert row["recovery_needed"] == 450.0

    def test_unrealized_uses_mid_minus_avg_open(
        self, reader: PositionMetricsReader
    ) -> None:
        """P&L Open = (mid - avg_open) * qty * mult * dir_sign, not just mid."""
        sym = CALL_SYMBOL
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="0.0",
                realized_gain_effect="Credit",
                is_open=True,
                open_entry_symbols=[sym],
            )
        )
        reader.trade_chains = {chain.id: chain}
        # Short 1x, sold at 2.00, now at 1.50 → profit = (2.00-1.50)*1*1000 = 500
        reader.position_metrics_df = make_position_df(
            [
                {
                    "symbol": sym,
                    "mid_price": 1.50,
                    "average_open_price": 2.00,
                    "quantity": 1.0,
                    "multiplier": 1000.0,
                    "quantity_direction": QuantityDirection.SHORT,
                }
            ]
        )
        df = reader.campaign_summary
        row = df.iloc[0]
        assert row["pnl_open"] == 500.0
        assert row["net_pnl"] == 500.0

    def test_long_position_unrealized(self, reader: PositionMetricsReader) -> None:
        sym = PUT_SYMBOL
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="0.0",
                realized_gain_effect="Credit",
                is_open=True,
                open_entry_symbols=[sym],
                open_entry_directions=["Long"],
            )
        )
        reader.trade_chains = {chain.id: chain}
        # Long 1x, bought at 1.0, now at 3.0 → profit = (3-1)*1*1000 = 2000
        reader.position_metrics_df = make_position_df(
            [
                {
                    "symbol": sym,
                    "mid_price": 3.0,
                    "average_open_price": 1.0,
                    "quantity": 1.0,
                    "multiplier": 1000.0,
                    "quantity_direction": QuantityDirection.LONG,
                }
            ]
        )
        df = reader.campaign_summary
        assert df.iloc[0]["pnl_open"] == 2000.0

    def test_net_pnl_combines_realized_and_unrealized(
        self, reader: PositionMetricsReader
    ) -> None:
        sym = CALL_SYMBOL
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="300.0",
                realized_gain_effect="Debit",
                is_open=True,
                open_entry_symbols=[sym],
                open_entry_directions=["Long"],
            )
        )
        reader.trade_chains = {chain.id: chain}
        # Long: (5-3)*1*100 = 200 unrealized
        reader.position_metrics_df = make_position_df(
            [
                {
                    "symbol": sym,
                    "mid_price": 5.0,
                    "average_open_price": 3.0,
                    "quantity": 1.0,
                    "multiplier": 100.0,
                    "quantity_direction": QuantityDirection.LONG,
                }
            ]
        )
        df = reader.campaign_summary
        row = df.iloc[0]
        assert row["realized_pnl"] == -300.0
        assert row["pnl_open"] == 200.0
        assert row["net_pnl"] == -100.0
        assert row["recovery_needed"] == 100.0

    def test_multiple_chains_same_underlying_aggregates(
        self, reader: PositionMetricsReader
    ) -> None:
        chain_a = TradeChain.model_validate_json(
            make_trade_chain_json(
                chain_id="aaa",
                underlying="/ZB",
                realized_gain="100.0",
                realized_gain_effect="Debit",
                total_fees="5.0",
                roll_count=1,
                is_open=False,
            )
        )
        chain_b = TradeChain.model_validate_json(
            make_trade_chain_json(
                chain_id="bbb",
                underlying="/ZB",
                realized_gain="50.0",
                realized_gain_effect="Debit",
                total_fees="3.0",
                roll_count=1,
                is_open=False,
            )
        )
        reader.trade_chains = {chain_a.id: chain_a, chain_b.id: chain_b}
        df = reader.campaign_summary
        assert len(df) == 1
        row = df.iloc[0]
        assert row["underlying"] == "/ZB"
        assert row["chains"] == 2
        assert row["total_rolls"] == 2
        assert row["realized_pnl"] == -150.0

    def test_missing_position_data_treated_as_zero_unrealized(
        self, reader: PositionMetricsReader
    ) -> None:
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="50.0",
                realized_gain_effect="Credit",
                is_open=True,
                open_entry_symbols=["UNKNOWN_SYMBOL"],
            )
        )
        reader.trade_chains = {chain.id: chain}
        df = reader.campaign_summary
        assert df.iloc[0]["pnl_open"] == 0.0
        assert df.iloc[0]["net_pnl"] == 50.0


# ---------------------------------------------------------------------------
# campaign_detail (TT-91)
# ---------------------------------------------------------------------------


class TestCampaignDetail:
    def test_empty_when_no_chains(self, reader: PositionMetricsReader) -> None:
        reader.trade_chains = {}
        result = reader.campaign_detail()
        assert result == []

    def test_detail_returns_chain_metadata(self, reader: PositionMetricsReader) -> None:
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="100.0",
                realized_gain_effect="Debit",
                total_fees="5.0",
                roll_count=2,
            )
        )
        reader.trade_chains = {chain.id: chain}
        result = reader.campaign_detail()
        assert len(result) == 1
        item = result[0]
        assert item["chain_id"] == "12345"
        assert item["description"] == "Strangle w/ a roll"
        assert item["underlying"] == "/6E"
        assert item["status"] == "open"
        assert item["rolls"] == 2
        assert item["realized_pnl"] == "-100.0"

    def test_detail_filtered_by_underlying(self, reader: PositionMetricsReader) -> None:
        chain_zb = TradeChain.model_validate_json(
            make_trade_chain_json(
                chain_id="zb1",
                underlying="/ZB",
                realized_gain="0.0",
                realized_gain_effect="Credit",
            )
        )
        chain_es = TradeChain.model_validate_json(
            make_trade_chain_json(
                chain_id="es1",
                underlying="/ES",
                realized_gain="0.0",
                realized_gain_effect="Credit",
            )
        )
        reader.trade_chains = {chain_zb.id: chain_zb, chain_es.id: chain_es}
        result = reader.campaign_detail(underlying="/ZB")
        assert len(result) == 1
        assert result[0]["underlying"] == "/ZB"

    def test_detail_includes_roll_flag_in_nodes(
        self, reader: PositionMetricsReader
    ) -> None:
        nodes = [
            {
                "node-type": "order",
                "id": "node1",
                "description": "Strangle",
                "occurred-at": "2026-03-07T15:30:00.000+0000",
                "total-fill-cost": "500.0",
                "total-fill-cost-effect": "Credit",
                "total-fees": "3.50",
                "roll": False,
                "legs": [
                    {
                        "symbol": CALL_SYMBOL,
                        "instrument-type": "Future Option",
                        "action": "Sell to Open",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    }
                ],
                "entries": [],
            },
            {
                "node-type": "order",
                "id": "node2",
                "description": "Rolling",
                "occurred-at": "2026-03-10T10:00:00.000+0000",
                "total-fill-cost": "50.0",
                "total-fill-cost-effect": "Debit",
                "total-fees": "3.50",
                "roll": True,
                "legs": [
                    {
                        "symbol": CALL_SYMBOL,
                        "instrument-type": "Future Option",
                        "action": "Buy to Close",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                    {
                        "symbol": PUT_SYMBOL,
                        "instrument-type": "Future Option",
                        "action": "Sell to Open",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                ],
                "entries": [],
            },
        ]
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="50.0",
                realized_gain_effect="Debit",
                total_fees="7.0",
                roll_count=1,
                lite_nodes=nodes,
                open_entry_symbols=[PUT_SYMBOL],
            )
        )
        reader.trade_chains = {chain.id: chain}
        result = reader.campaign_detail()
        detail_nodes = result[0]["nodes"]
        assert len(detail_nodes) == 2
        assert detail_nodes[0]["roll"] is False
        assert detail_nodes[0]["description"] == "Strangle"
        assert detail_nodes[0]["fill_cost"] == "500.0"
        assert detail_nodes[1]["roll"] is True
        assert detail_nodes[1]["description"] == "Rolling"
        assert detail_nodes[1]["fill_cost"] == "-50.0"
        # Check legs
        assert len(detail_nodes[1]["legs"]) == 2
        assert detail_nodes[1]["legs"][0]["action"] == "Buy to Close"

    def test_detail_open_legs_with_mark_values(
        self, reader: PositionMetricsReader
    ) -> None:
        sym = PUT_SYMBOL
        chain = TradeChain.model_validate_json(
            make_trade_chain_json(
                realized_gain="0.0",
                realized_gain_effect="Credit",
                is_open=True,
                open_entry_symbols=[sym],
            )
        )
        reader.trade_chains = {chain.id: chain}
        reader.position_metrics_df = make_position_df(
            [
                {
                    "symbol": sym,
                    "mid_price": 3.0,
                    "average_open_price": 2.0,
                    "quantity": 1.0,
                    "multiplier": 1000.0,
                    "quantity_direction": QuantityDirection.SHORT,
                }
            ]
        )
        result = reader.campaign_detail()
        open_legs = result[0]["open_legs"]
        assert len(open_legs) == 1
        assert open_legs[0]["symbol"] == sym
        assert open_legs[0]["direction"] == "Short"
        # Short: -(3.0 - 2.0) * 1 * 1000 = -1000
        assert open_legs[0]["pnl_open"] == -1000.0
