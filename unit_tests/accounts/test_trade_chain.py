"""Tests for TT-80 TradeChain pipeline — OrderChain parsing, routing, and publishing."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.accounts.models import TradeChain
from tastytrade.accounts.orchestrator import consume_order_chains
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.accounts.streamer import AccountStreamer
from tastytrade.config.enumerations import AccountEventType


# ---------------------------------------------------------------------------
# Helpers — factory functions for TradeChain payloads
# ---------------------------------------------------------------------------


def make_trade_chain_data(**overrides: Any) -> dict[str, Any]:
    """Minimal OrderChain event payload matching live production structure."""
    base: dict[str, Any] = {
        "id": "12345",
        "description": "Iron Condor",
        "underlying-symbol": "RUT",
        "computed-data": {
            "open": True,
            "total-fees": "1.26",
            "total-fees-effect": "Debit",
            "total-commissions": "2.00",
            "total-commissions-effect": "Debit",
            "realized-gain": "0.0",
            "realized-gain-effect": "None",
            "realized-gain-with-fees": "-3.26",
            "realized-gain-with-fees-effect": "Debit",
            "winner-realized-and-closed": False,
            "winner-realized": False,
            "winner-realized-with-fees": False,
            "roll-count": 0,
            "opened-at": "2026-03-07T15:30:00.000+0000",
            "last-occurred-at": "2026-03-07T15:30:00.000+0000",
            "total-opening-cost": "2.50",
            "total-opening-cost-effect": "Credit",
            "open-entries": [
                {
                    "symbol": "RUT   260320P02050000",
                    "instrument-type": "Equity Option",
                    "quantity": "1",
                    "quantity-type": "Short",
                    "quantity-numeric": "-1",
                },
            ],
        },
        "lite-nodes-sizes": 1,
        "lite-nodes": [
            {
                "node-type": "order",
                "id": "node-1",
                "description": "Iron Condor",
                "occurred-at": "2026-03-07T15:30:00.000+0000",
                "total-fees": "1.26",
                "total-fees-effect": "Debit",
                "total-fill-cost": "2.50",
                "total-fill-cost-effect": "Credit",
                "gcd-quantity": "1",
                "fill-cost-per-quantity": "2.50",
                "fill-cost-per-quantity-effect": "Credit",
                "order-fill-count": 1,
                "roll": False,
                "legs": [
                    {
                        "symbol": "RUT   260320P02050000",
                        "instrument-type": "Equity Option",
                        "action": "Sell to Open",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                ],
                "entries": [],
            },
        ],
    }
    base.update(overrides)
    return base


def make_closed_trade_chain_data() -> dict[str, Any]:
    """OrderChain for a closed (realized P&L) trade."""
    return make_trade_chain_data(
        id="67890",
        description="Vertical",
        **{
            "underlying-symbol": "/ES",
            "computed-data": {
                "open": False,
                "realized-gain": "150.0",
                "realized-gain-effect": "Credit",
                "realized-gain-with-fees": "146.74",
                "realized-gain-with-fees-effect": "Credit",
                "winner-realized-and-closed": True,
                "winner-realized": True,
                "winner-realized-with-fees": True,
                "roll-count": 1,
                "opened-at": "2026-03-01T10:00:00.000+0000",
                "last-occurred-at": "2026-03-07T14:00:00.000+0000",
                "total-opening-cost": "5.00",
                "total-opening-cost-effect": "Debit",
                "total-closing-cost": "1.50",
                "total-closing-cost-effect": "Credit",
                "total-cost": "150.0",
                "total-cost-effect": "Credit",
                "total-fees": "3.26",
                "total-fees-effect": "Debit",
                "total-commissions": "4.00",
                "total-commissions-effect": "Debit",
                "open-entries": [],
            },
        },
    )


def fresh_streamer() -> AccountStreamer:
    """Create a fresh AccountStreamer with no singleton state."""
    AccountStreamer.instance = None
    streamer = AccountStreamer.__new__(AccountStreamer)
    streamer.credentials = None
    streamer.reconnect_signal = None
    streamer.queues = {event_type: asyncio.Queue() for event_type in AccountEventType}
    streamer.request_id = 0
    streamer.websocket = None
    streamer.session = None
    streamer.listener_task = None
    streamer.keepalive_task = None
    streamer.initialized = True
    return streamer


# ---------------------------------------------------------------------------
# AccountEventType enum
# ---------------------------------------------------------------------------


def test_order_chain_event_type_value() -> None:
    assert AccountEventType.ORDER_CHAIN.value == "OrderChain"


def test_order_chain_queue_created_for_all_event_types() -> None:
    streamer = fresh_streamer()
    assert AccountEventType.ORDER_CHAIN in streamer.queues


# ---------------------------------------------------------------------------
# TradeChain model parsing
# ---------------------------------------------------------------------------


class TestTradeChainModel:
    def test_parse_open_chain(self) -> None:
        data = make_trade_chain_data()
        chain = TradeChain.model_validate(data)
        assert chain.id == "12345"
        assert chain.description == "Iron Condor"
        assert chain.underlying_symbol == "RUT"
        assert chain.computed_data.open is True
        assert chain.computed_data.roll_count == 0

    def test_parse_closed_chain(self) -> None:
        data = make_closed_trade_chain_data()
        chain = TradeChain.model_validate(data)
        assert chain.id == "67890"
        assert chain.description == "Vertical"
        assert chain.underlying_symbol == "/ES"
        assert chain.computed_data.open is False
        assert chain.computed_data.roll_count == 1
        assert chain.computed_data.realized_gain == "150.0"
        assert chain.computed_data.winner_realized_and_closed is True

    def test_lite_nodes_parsed(self) -> None:
        data = make_trade_chain_data()
        chain = TradeChain.model_validate(data)
        assert len(chain.lite_nodes) == 1
        node = chain.lite_nodes[0]
        assert node.node_type == "order"
        assert node.description == "Iron Condor"
        assert len(node.legs) == 1
        assert node.legs[0].action == "Sell to Open"

    def test_computed_data_open_entries(self) -> None:
        data = make_trade_chain_data()
        chain = TradeChain.model_validate(data)
        entries = chain.computed_data.open_entries
        assert len(entries) == 1
        assert entries[0].quantity_type == "Short"

    def test_extra_fields_preserved(self) -> None:
        """TradeChain uses extra='allow' — unknown fields must not be rejected."""
        data = make_trade_chain_data()
        data["new-brokerage-field"] = "future-value"
        chain = TradeChain.model_validate(data)
        assert chain.id == "12345"


# ---------------------------------------------------------------------------
# parse_event — OrderChain routing
# ---------------------------------------------------------------------------


class TestParseEventOrderChain:
    def test_parse_event_returns_trade_chain(self) -> None:
        data = make_trade_chain_data()
        result = AccountStreamer.parse_event("OrderChain", data)
        assert isinstance(result, TradeChain)
        assert result.id == "12345"

    def test_parse_event_invalid_data_returns_none(self) -> None:
        result = AccountStreamer.parse_event("OrderChain", {"bad": "data"})
        assert result is None


# ---------------------------------------------------------------------------
# handle_event — OrderChain enqueue
# ---------------------------------------------------------------------------


class TestHandleEventOrderChain:
    def test_routes_order_chain_to_queue(self) -> None:
        streamer = fresh_streamer()
        event_data = {
            "type": "OrderChain",
            "data": make_trade_chain_data(),
        }
        streamer.handle_event(event_data)
        queue = streamer.queues[AccountEventType.ORDER_CHAIN]
        assert not queue.empty()
        item = queue.get_nowait()
        assert isinstance(item, TradeChain)
        assert item.underlying_symbol == "RUT"

    def test_closed_chain_routes_correctly(self) -> None:
        streamer = fresh_streamer()
        event_data = {
            "type": "OrderChain",
            "data": make_closed_trade_chain_data(),
        }
        streamer.handle_event(event_data)
        item = streamer.queues[AccountEventType.ORDER_CHAIN].get_nowait()
        assert isinstance(item, TradeChain)
        assert item.computed_data.open is False


# ---------------------------------------------------------------------------
# publish_trade_chain
# ---------------------------------------------------------------------------


class TestPublishTradeChain:
    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def publisher(self, mock_redis: AsyncMock) -> AccountStreamPublisher:
        pub = AccountStreamPublisher.__new__(AccountStreamPublisher)
        pub.redis = mock_redis
        return pub

    def test_trade_chain_redis_keys(self) -> None:
        assert AccountStreamPublisher.TRADE_CHAINS_KEY == "tastytrade:trade_chains"
        assert (
            AccountStreamPublisher.TRADE_CHAIN_CHANNEL == "tastytrade:events:OrderChain"
        )

    @pytest.mark.asyncio
    async def test_publish_trade_chain_writes_hset(
        self, publisher: AccountStreamPublisher, mock_redis: AsyncMock
    ) -> None:
        chain = TradeChain.model_validate(make_trade_chain_data())
        await publisher.publish_trade_chain(chain)
        mock_redis.hset.assert_called_once()
        call_args = mock_redis.hset.call_args
        assert call_args[0][0] == "tastytrade:trade_chains"
        assert call_args[0][1] == "12345"

    @pytest.mark.asyncio
    async def test_publish_trade_chain_publishes_pubsub(
        self, publisher: AccountStreamPublisher, mock_redis: AsyncMock
    ) -> None:
        chain = TradeChain.model_validate(make_trade_chain_data())
        await publisher.publish_trade_chain(chain)
        mock_redis.publish.assert_called_once()
        channel = mock_redis.publish.call_args[1]["channel"]
        assert channel == "tastytrade:events:OrderChain"


# ---------------------------------------------------------------------------
# consume_order_chains
# ---------------------------------------------------------------------------


class TestConsumeOrderChains:
    @pytest.mark.asyncio
    async def test_drains_queue_and_publishes(self) -> None:
        queue: asyncio.Queue[TradeChain] = asyncio.Queue()
        mock_publisher = AsyncMock()

        chain = MagicMock(spec=TradeChain)
        queue.put_nowait(chain)

        task = asyncio.create_task(consume_order_chains(queue, mock_publisher))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        mock_publisher.publish_trade_chain.assert_awaited_once_with(chain)

    @pytest.mark.asyncio
    async def test_handles_multiple_chains(self) -> None:
        queue: asyncio.Queue[TradeChain] = asyncio.Queue()
        mock_publisher = AsyncMock()

        chain1 = MagicMock(spec=TradeChain)
        chain2 = MagicMock(spec=TradeChain)
        queue.put_nowait(chain1)
        queue.put_nowait(chain2)

        task = asyncio.create_task(consume_order_chains(queue, mock_publisher))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_publisher.publish_trade_chain.await_count == 2
