"""Tests for the live-fill entry credit monitor (TT-79, TT-87).

Tests cover fill-driven entry credit computation directly from order fill
data — no position lookup or REST API dependency.
"""

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.accounts.models import (
    InstrumentType,
    OrderAction,
    OrderFill,
    OrderLeg,
    OrderStatus,
    PlacedOrder,
)
from tastytrade.accounts.orchestrator import (
    compute_leg_entry_credit,
    monitor_fills_for_entry_credits,
    resolve_multiplier,
)


def make_order(
    status: OrderStatus = OrderStatus.FILLED,
    legs: list[OrderLeg] | None = None,
    underlying_symbol: str = "SPY",
) -> PlacedOrder:
    """Create a minimal PlacedOrder for testing."""
    if legs is None:
        legs = []
    return PlacedOrder.model_construct(
        id=1,
        account_number="TEST123",
        status=status,
        legs=legs,
        order_type="Limit",
        time_in_force="Day",
        underlying_symbol=underlying_symbol,
    )


def make_fill(
    fill_price: float = 5.0,
    quantity: float = 1.0,
) -> OrderFill:
    """Create a minimal OrderFill for testing."""
    return OrderFill.model_construct(
        fill_id="test-fill-1",
        quantity=quantity,
        fill_price=fill_price,
        filled_at="2026-03-16T20:00:00Z",
    )


def make_leg(
    symbol: str = "SPY   260430C00500000",
    instrument_type: InstrumentType = InstrumentType.EQUITY_OPTION,
    action: OrderAction = OrderAction.SELL_TO_OPEN,
    quantity: float = 1.0,
    fills: list[OrderFill] | None = None,
) -> OrderLeg:
    """Create an OrderLeg for testing."""
    return OrderLeg.model_construct(
        instrument_type=instrument_type,
        symbol=symbol,
        action=action,
        quantity=quantity,
        remaining_quantity=0.0,
        fills=fills or [],
    )


# === compute_leg_entry_credit tests ===


class TestComputeLegEntryCredit:
    def test_sell_to_open_is_credit(self) -> None:
        """Sell to Open fill → positive entry value (credit received)."""
        leg = make_leg(
            action=OrderAction.SELL_TO_OPEN,
            fills=[make_fill(fill_price=3.50, quantity=2.0)],
        )
        credit = compute_leg_entry_credit(leg, Decimal("100"))
        # 3.50 × 2 × 100 × +1 = 700
        assert credit.value == Decimal("700")
        assert credit.per_unit_price == Decimal("3.50")
        assert credit.method == "order_fill"

    def test_buy_to_open_is_debit(self) -> None:
        """Buy to Open fill → negative entry value (debit paid)."""
        leg = make_leg(
            action=OrderAction.BUY_TO_OPEN,
            fills=[make_fill(fill_price=2.00, quantity=1.0)],
        )
        credit = compute_leg_entry_credit(leg, Decimal("100"))
        # 2.00 × 1 × 100 × -1 = -200
        assert credit.value == Decimal("-200")

    def test_multiple_fills_summed(self) -> None:
        """Multiple partial fills sum correctly."""
        leg = make_leg(
            action=OrderAction.SELL_TO_OPEN,
            fills=[
                make_fill(fill_price=3.00, quantity=1.0),
                make_fill(fill_price=3.20, quantity=1.0),
            ],
        )
        credit = compute_leg_entry_credit(leg, Decimal("100"))
        # (3.00 × 1 + 3.20 × 1) × 100 = 620
        assert credit.value == Decimal("620")
        # Weighted avg: (3.00 + 3.20) / 2 = 3.10
        assert credit.per_unit_price == Decimal("3.10")

    def test_futures_multiplier(self) -> None:
        """Future option uses notional multiplier (e.g., /6E = 125000)."""
        leg = make_leg(
            symbol="./6EM6 EUUK6 260508C1.2",
            instrument_type=InstrumentType.FUTURE_OPTION,
            action=OrderAction.SELL_TO_OPEN,
            fills=[make_fill(fill_price=0.003, quantity=2.0)],
        )
        credit = compute_leg_entry_credit(leg, Decimal("125000"))
        # 0.003 × 2 × 125000 = 750
        assert credit.value == Decimal("750")

    def test_symbol_preserved(self) -> None:
        """Entry credit symbol matches the leg symbol."""
        leg = make_leg(
            symbol="QQQ   260430P00575000",
            action=OrderAction.SELL_TO_OPEN,
            fills=[make_fill(fill_price=8.32, quantity=1.0)],
        )
        credit = compute_leg_entry_credit(leg, Decimal("100"))
        assert credit.symbol == "QQQ   260430P00575000"


# === resolve_multiplier tests ===


class TestResolveMultiplier:
    @pytest.mark.asyncio
    async def test_equity_option_from_position(self) -> None:
        """Equity option reads multiplier from Position in Redis."""
        redis_client = AsyncMock()
        pos_data = json.dumps({"multiplier": 100}).encode()
        redis_client.hget.return_value = pos_data

        leg = make_leg(instrument_type=InstrumentType.EQUITY_OPTION)
        result = await resolve_multiplier(redis_client, leg)
        assert result == Decimal("100")

    @pytest.mark.asyncio
    async def test_equity_option_defaults_to_100(self) -> None:
        """Equity option defaults to 100 when position not in Redis."""
        redis_client = AsyncMock()
        redis_client.hget.return_value = None

        leg = make_leg(instrument_type=InstrumentType.EQUITY_OPTION)
        result = await resolve_multiplier(redis_client, leg)
        assert result == Decimal("100")

    @pytest.mark.asyncio
    async def test_future_option_from_position(self) -> None:
        """Future option reads multiplier from Position in Redis."""
        redis_client = AsyncMock()
        pos_data = json.dumps({"multiplier": 125000.0}).encode()
        redis_client.hget.return_value = pos_data

        leg = make_leg(
            symbol="./6EM6 EUUK6 260508C1.2",
            instrument_type=InstrumentType.FUTURE_OPTION,
        )
        result = await resolve_multiplier(redis_client, leg)
        assert result == Decimal("125000.0")

    @pytest.mark.asyncio
    async def test_future_option_missing_position_defaults_to_1(self) -> None:
        """Future option defaults to 1 when position not in Redis."""
        redis_client = AsyncMock()
        redis_client.hget.return_value = None

        leg = make_leg(instrument_type=InstrumentType.FUTURE_OPTION)
        result = await resolve_multiplier(redis_client, leg)
        assert result == Decimal("1")


# === monitor_fills_for_entry_credits integration tests ===


def make_pubsub_message(order: PlacedOrder) -> dict[str, object]:
    """Create a Redis pub/sub message dict from a PlacedOrder."""
    return {
        "type": "message",
        "data": order.model_dump_json(by_alias=True),
    }


class TestMonitorFillsForEntryCredits:
    @pytest.mark.asyncio
    async def test_open_fill_computes_entry_credit(self) -> None:
        """FILLED order with Sell to Open legs → entry credits published."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[
                make_leg(
                    symbol="SPY   260430C00693000",
                    action=OrderAction.SELL_TO_OPEN,
                    fills=[make_fill(fill_price=6.42, quantity=1.0)],
                ),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter([make_pubsub_message(order)])
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)
        # Position with multiplier = 100 (equity option)
        redis_client.hget.return_value = json.dumps({"multiplier": 100}).encode()

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        await run_monitor_briefly(redis_client, publisher)

        publisher.publish_entry_credits.assert_called_once()
        credits = publisher.publish_entry_credits.call_args[0][0]
        assert "SPY   260430C00693000" in credits
        assert credits["SPY   260430C00693000"].value == Decimal("642")

    @pytest.mark.asyncio
    async def test_buy_to_open_computes_debit(self) -> None:
        """Buy to Open fills produce negative entry values."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[
                make_leg(
                    symbol="SPY   260430P00638000",
                    action=OrderAction.BUY_TO_OPEN,
                    fills=[make_fill(fill_price=7.01, quantity=1.0)],
                ),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter([make_pubsub_message(order)])
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)
        # Position with multiplier = 100 (equity option)
        redis_client.hget.return_value = json.dumps({"multiplier": 100}).encode()

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        await run_monitor_briefly(redis_client, publisher)

        credits = publisher.publish_entry_credits.call_args[0][0]
        assert credits["SPY   260430P00638000"].value == Decimal("-701")

    @pytest.mark.asyncio
    async def test_multi_leg_order_computes_all_open_legs(self) -> None:
        """Iron condor: all 4 open legs get entry credits from a single order."""
        order = make_order(
            status=OrderStatus.FILLED,
            underlying_symbol="/RTYM6",
            legs=[
                make_leg(
                    symbol="./RTYM6RTMJ6 260430C2750",
                    instrument_type=InstrumentType.FUTURE_OPTION,
                    action=OrderAction.SELL_TO_OPEN,
                    fills=[make_fill(fill_price=14.5, quantity=2.0)],
                ),
                make_leg(
                    symbol="./RTYM6RTMJ6 260430C2775",
                    instrument_type=InstrumentType.FUTURE_OPTION,
                    action=OrderAction.BUY_TO_OPEN,
                    fills=[make_fill(fill_price=9.5, quantity=2.0)],
                ),
                make_leg(
                    symbol="./RTYM6RTMJ6 260430P2275",
                    instrument_type=InstrumentType.FUTURE_OPTION,
                    action=OrderAction.SELL_TO_OPEN,
                    fills=[make_fill(fill_price=25.8, quantity=2.0)],
                ),
                make_leg(
                    symbol="./RTYM6RTMJ6 260430P2250",
                    instrument_type=InstrumentType.FUTURE_OPTION,
                    action=OrderAction.BUY_TO_OPEN,
                    fills=[make_fill(fill_price=20.0, quantity=2.0)],
                ),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter([make_pubsub_message(order)])
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)
        # Position multiplier for /RTY future options = 50
        redis_client.hget.return_value = json.dumps({"multiplier": 50.0}).encode()

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        await run_monitor_briefly(redis_client, publisher)

        credits = publisher.publish_entry_credits.call_args[0][0]
        assert len(credits) == 4
        # Short call: 14.5 × 2 × 50 = 1450
        assert credits["./RTYM6RTMJ6 260430C2750"].value == Decimal("1450")
        # Long call: 9.5 × 2 × 50 × -1 = -950
        assert credits["./RTYM6RTMJ6 260430C2775"].value == Decimal("-950")

    @pytest.mark.asyncio
    async def test_close_fills_are_ignored(self) -> None:
        """Close actions (Buy/Sell to Close) do not produce entry credits."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[
                make_leg(
                    symbol="SPY   260417C00699000",
                    action=OrderAction.BUY_TO_CLOSE,
                    fills=[make_fill(fill_price=5.0, quantity=1.0)],
                ),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter([make_pubsub_message(order)])
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"

        await run_monitor_briefly(redis_client, publisher)

        publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_filled_order_is_ignored(self) -> None:
        """Orders with status != FILLED should not trigger processing."""
        for status in [OrderStatus.ROUTED, OrderStatus.LIVE, OrderStatus.CANCELLED]:
            order = make_order(
                status=status,
                legs=[
                    make_leg(
                        action=OrderAction.SELL_TO_OPEN,
                        fills=[make_fill()],
                    ),
                ],
            )

            pubsub_mock = AsyncMock()
            pubsub_mock.listen = MagicMock(
                return_value=_async_iter([make_pubsub_message(order)])
            )

            redis_client = AsyncMock()
            redis_client.pubsub = MagicMock(return_value=pubsub_mock)

            publisher = AsyncMock()
            publisher.ORDER_CHANNEL = "tastytrade:events:Order"

            await run_monitor_briefly(redis_client, publisher)

            publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_option_legs_are_ignored(self) -> None:
        """Equity and future legs in a filled order don't produce entry credits."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[
                make_leg(
                    symbol="AAPL",
                    instrument_type=InstrumentType.EQUITY,
                    action=OrderAction.BUY_TO_OPEN,
                    fills=[make_fill()],
                ),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter([make_pubsub_message(order)])
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"

        await run_monitor_briefly(redis_client, publisher)

        publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_message_is_logged_and_skipped(self) -> None:
        """ValidationError on bad payload should not crash the monitor."""
        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter([{"type": "message", "data": b"not valid json"}])
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"

        await run_monitor_briefly(redis_client, publisher)

        publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscribe_message_is_skipped(self) -> None:
        """Redis subscribe control messages should be silently ignored."""
        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    {"type": "subscribe", "data": 1},
                    {"type": "psubscribe", "data": 1},
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"

        await run_monitor_briefly(redis_client, publisher)

        publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_legs_without_fills_are_skipped(self) -> None:
        """Open legs with empty fills array don't produce entry credits."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[
                make_leg(
                    action=OrderAction.SELL_TO_OPEN,
                    fills=[],  # No fills
                ),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter([make_pubsub_message(order)])
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"

        await run_monitor_briefly(redis_client, publisher)

        publisher.publish_entry_credits.assert_not_called()


# === Helpers ===


async def _async_iter(items: list[dict[str, object]]):  # type: ignore[type-arg]
    """Yield items as an async iterator, then block until cancelled."""
    for item in items:
        yield item
    await asyncio.get_event_loop().create_future()


async def run_monitor_briefly(
    redis_client: AsyncMock,
    publisher: AsyncMock,
    timeout: float = 0.05,
) -> None:
    """Run the fill monitor and cancel it after a brief timeout."""
    influx = MagicMock()
    task = asyncio.create_task(
        monitor_fills_for_entry_credits(redis_client, publisher, influx, "TEST00001")
    )
    await asyncio.sleep(timeout)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
