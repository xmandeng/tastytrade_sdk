"""Tests for TradeChain pipeline — OrderChain parsing, routing, publishing, and Greeks extraction."""

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.accounts.models import TradeChain
from tastytrade.accounts.orchestrator import (
    consume_order_chains,
    extract_execution_greeks,
    safe_float,
)
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
        mock_influx = MagicMock()
        stop = asyncio.Event()

        chain = MagicMock(spec=TradeChain)
        chain.lite_nodes = []
        queue.put_nowait(chain)

        task = asyncio.create_task(
            consume_order_chains(queue, mock_publisher, mock_influx, stop)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await task

        mock_publisher.publish_trade_chain.assert_awaited_once_with(chain)
        mock_influx.process_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_multiple_chains(self) -> None:
        queue: asyncio.Queue[TradeChain] = asyncio.Queue()
        mock_publisher = AsyncMock()
        mock_influx = MagicMock()
        stop = asyncio.Event()

        chain1 = MagicMock(spec=TradeChain)
        chain1.lite_nodes = []
        chain2 = MagicMock(spec=TradeChain)
        chain2.lite_nodes = []
        queue.put_nowait(chain1)
        queue.put_nowait(chain2)

        task = asyncio.create_task(
            consume_order_chains(queue, mock_publisher, mock_influx, stop)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await task

        assert mock_publisher.publish_trade_chain.await_count == 2


# ---------------------------------------------------------------------------
# extract_execution_greeks — TT-86
# ---------------------------------------------------------------------------


def make_iron_condor_chain_data() -> dict[str, Any]:
    """Iron Condor with 4 option legs + underlying in market-state-snapshot.

    Based on real production /RTY Iron Condor data from Redis.
    """
    return {
        "id": "149452436",
        "description": "Iron Condor",
        "underlying-symbol": "/RTY",
        "computed-data": {
            "open": False,
            "total-fees": "3.26",
            "total-fees-effect": "Debit",
            "total-commissions": "4.00",
            "total-commissions-effect": "Debit",
            "realized-gain": "150.0",
            "realized-gain-effect": "Credit",
            "realized-gain-with-fees": "146.74",
            "realized-gain-with-fees-effect": "Credit",
            "winner-realized-and-closed": True,
            "winner-realized": True,
            "winner-realized-with-fees": True,
            "roll-count": 0,
            "opened-at": "2026-02-24T01:15:31.361+0000",
            "last-occurred-at": "2026-03-09T04:34:18.957+0000",
            "open-entries": [],
        },
        "lite-nodes-sizes": 2,
        "lite-nodes": [
            {
                "node-type": "order",
                "id": "close-node",
                "description": "Closing",
                "occurred-at": "2026-03-09T04:34:18.957+0000",
                "legs": [
                    {
                        "symbol": "./RTYM6RTMH6 260331C2825",
                        "instrument-type": "Future Option",
                        "action": "Buy to Close",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                    {
                        "symbol": "./RTYM6RTMH6 260331C2875",
                        "instrument-type": "Future Option",
                        "action": "Sell to Close",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                ],
                "entries": [],
                "market-state-snapshot": {
                    "total-delta": "0.00848133",
                    "total-theta": "-0.057309664",
                    "market-datas": [
                        {
                            "symbol": "/RTYM6",
                            "instrument-type": "Future",
                            "bid": "2446.7",
                            "ask": "2448.2",
                            "last": "2447.7",
                        },
                        {
                            "symbol": "./RTYM6RTMH6 260331C2875",
                            "instrument-type": "Future Option",
                            "bid": "0.35",
                            "ask": "4.1",
                            "last": "4.5",
                            "delta": "0.021822923",
                            "gamma": "0.000272795",
                            "theta": "-0.220111445",
                            "vega": "0.318189025",
                            "rho": "0.032276846",
                        },
                        {
                            "symbol": "./RTYM6RTMH6 260331C2825",
                            "instrument-type": "Future Option",
                            "bid": "0.85",
                            "ask": "4.0",
                            "last": "3.7",
                            "delta": "0.030304253",
                            "gamma": "0.000375122",
                            "theta": "-0.277421109",
                            "vega": "0.418814738",
                            "rho": "0.04482087",
                        },
                    ],
                },
            },
            {
                "node-type": "order",
                "id": "entry-node",
                "description": "Iron Condor",
                "occurred-at": "2026-02-24T01:15:31.361+0000",
                "legs": [
                    {
                        "symbol": "./RTYM6RTMH6 260331P2390",
                        "instrument-type": "Future Option",
                        "action": "Buy to Open",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                    {
                        "symbol": "./RTYM6RTMH6 260331C2875",
                        "instrument-type": "Future Option",
                        "action": "Buy to Open",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                    {
                        "symbol": "./RTYM6RTMH6 260331C2825",
                        "instrument-type": "Future Option",
                        "action": "Sell to Open",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                    {
                        "symbol": "./RTYM6RTMH6 260331P2425",
                        "instrument-type": "Future Option",
                        "action": "Sell to Open",
                        "fill-quantity": "1",
                        "order-quantity": "1",
                    },
                ],
                "entries": [],
                "market-state-snapshot": {
                    "total-delta": "-0.0353321",
                    "total-theta": "0.270851799",
                    "market-datas": [
                        {
                            "symbol": "/RTYM6",
                            "instrument-type": "Future",
                            "bid": "2644.2",
                            "ask": "2645.8",
                            "last": "2645.7",
                        },
                        {
                            "symbol": "./RTYM6RTMH6 260331C2825",
                            "instrument-type": "Future Option",
                            "bid": "14.8",
                            "ask": "15.5",
                            "last": "20.25",
                            "delta": "0.168127035",
                            "gamma": "0.001436204",
                            "theta": "-0.610395962",
                            "vega": "2.080064079",
                            "rho": "0.421770017",
                        },
                        {
                            "symbol": "./RTYM6RTMH6 260331C2875",
                            "instrument-type": "Future Option",
                            "bid": "7.8",
                            "ask": "8.4",
                            "last": "9.0",
                            "delta": "0.103205876",
                            "gamma": "0.001055912",
                            "theta": "-0.424558728",
                            "vega": "1.487111087",
                            "rho": "0.26007651",
                        },
                        {
                            "symbol": "./RTYM6RTMH6 260331P2425",
                            "instrument-type": "Future Option",
                            "bid": "23.25",
                            "ask": "24.25",
                            "last": "27.75",
                            "delta": "-0.168194071",
                            "gamma": "0.000991411",
                            "theta": "-0.882669196",
                            "vega": "2.080596965",
                            "rho": "-0.460188964",
                        },
                        {
                            "symbol": "./RTYM6RTMH6 260331P2390",
                            "instrument-type": "Future Option",
                            "bid": "18.9",
                            "ask": "19.6",
                            "last": "21.75",
                            "delta": "-0.138605012",
                            "gamma": "0.000849381",
                            "theta": "-0.797654631",
                            "vega": "1.830363501",
                            "rho": "-0.378824782",
                        },
                    ],
                },
            },
        ],
    }


class TestSafeFloat:
    def test_valid_string(self) -> None:
        assert safe_float("0.123") == 0.123

    def test_negative(self) -> None:
        assert safe_float("-0.5") == -0.5

    def test_none(self) -> None:
        assert safe_float(None) is None

    def test_invalid_string(self) -> None:
        assert safe_float("bad") is None


class TestExtractTradeChainGreeks:
    def test_iron_condor_produces_per_leg_and_aggregate(self) -> None:
        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        points = extract_execution_greeks(chain)

        # 2 nodes: close (2 option legs + 1 agg) + entry (4 option legs + 1 agg) = 8
        assert len(points) == 8

        per_leg = [p for p in points if p.__class__.__name__ == "TradeChainGreeks"]
        aggregate = [p for p in points if p.__class__.__name__ == "TradeChainGreeksNet"]
        assert len(per_leg) == 6  # 2 close legs + 4 entry legs
        assert len(aggregate) == 2  # 1 per node

    def test_per_leg_point_has_correct_fields(self) -> None:
        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        points = extract_execution_greeks(chain)

        # First per-leg point is from the close node
        leg = next(p for p in points if p.__class__.__name__ == "TradeChainGreeks")
        assert leg.chain_id == "149452436"
        assert leg.underlying == "/RTY"
        assert leg.strategy == "Iron Condor"
        assert isinstance(leg.delta, float)
        assert isinstance(leg.gamma, float)
        assert isinstance(leg.theta, float)
        assert isinstance(leg.vega, float)
        assert isinstance(leg.rho, float)
        assert isinstance(leg.bid, float)
        assert isinstance(leg.ask, float)
        # Underlying spot prices carried through
        assert leg.underlying_bid == 2446.7
        assert leg.underlying_ask == 2448.2
        assert leg.underlying_last == 2447.7

    def test_aggregate_point_has_total_greeks(self) -> None:
        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        points = extract_execution_greeks(chain)

        # First aggregate is from the close node
        agg = next(p for p in points if p.__class__.__name__ == "TradeChainGreeksNet")
        assert agg.eventSymbol == "/RTY"
        assert agg.total_delta == pytest.approx(0.00848133)
        assert agg.total_theta == pytest.approx(-0.057309664)
        assert agg.underlying_bid == 2446.7

    def test_entry_node_has_four_legs(self) -> None:
        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        points = extract_execution_greeks(chain)

        # Entry node is second — filter by its timestamp
        entry_legs = [
            p
            for p in points
            if p.__class__.__name__ == "TradeChainGreeks"
            and p.node_description == "Iron Condor"
        ]
        assert len(entry_legs) == 4

        symbols = {p.eventSymbol for p in entry_legs}
        assert "./RTYM6RTMH6 260331C2825" in symbols
        assert "./RTYM6RTMH6 260331C2875" in symbols
        assert "./RTYM6RTMH6 260331P2425" in symbols
        assert "./RTYM6RTMH6 260331P2390" in symbols

    def test_entry_aggregate_has_correct_values(self) -> None:
        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        points = extract_execution_greeks(chain)

        entry_agg = [
            p
            for p in points
            if p.__class__.__name__ == "TradeChainGreeksNet"
            and p.node_description == "Iron Condor"
        ]
        assert len(entry_agg) == 1
        assert entry_agg[0].total_delta == pytest.approx(-0.0353321)
        assert entry_agg[0].total_theta == pytest.approx(0.270851799)
        assert entry_agg[0].underlying_bid == 2644.2

    def test_measurement_names_for_influx(self) -> None:
        """SimpleNamespace class names must match expected InfluxDB measurements."""
        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        points = extract_execution_greeks(chain)

        class_names = {p.__class__.__name__ for p in points}
        assert class_names == {"TradeChainGreeks", "TradeChainGreeksNet"}

    def test_timestamps_are_datetime_objects(self) -> None:
        """process_event() requires time to be a datetime, not a string."""
        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        points = extract_execution_greeks(chain)

        for point in points:
            assert hasattr(point, "time")
            assert isinstance(point.time, datetime)

    def test_node_without_snapshot_is_skipped(self) -> None:
        data = make_trade_chain_data()  # No market-state-snapshot
        chain = TradeChain.model_validate(data)
        points = extract_execution_greeks(chain)
        assert points == []

    def test_node_without_occurred_at_is_skipped(self) -> None:
        data = make_iron_condor_chain_data()
        data["lite-nodes"][0]["occurred-at"] = None
        chain = TradeChain.model_validate(data)
        points = extract_execution_greeks(chain)

        # Only the entry node should produce points (4 legs + 1 agg = 5)
        assert len(points) == 5


class TestConsumeOrderChainsWithGreeks:
    @pytest.mark.asyncio
    async def test_writes_greeks_points_to_influx(self) -> None:
        queue: asyncio.Queue[TradeChain] = asyncio.Queue()
        mock_publisher = AsyncMock()
        mock_influx = MagicMock()
        stop = asyncio.Event()

        chain = TradeChain.model_validate(make_iron_condor_chain_data())
        queue.put_nowait(chain)

        task = asyncio.create_task(
            consume_order_chains(queue, mock_publisher, mock_influx, stop)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await task

        # 1 chain.for_influx() + 8 greeks points = 9 calls
        assert mock_influx.process_event.call_count == 9

        # Verify measurement names in the calls
        class_names = {
            call.args[0].__class__.__name__
            for call in mock_influx.process_event.call_args_list
        }
        assert "TradeChainGreeks" in class_names
        assert "TradeChainGreeksNet" in class_names
