"""Tests for the live-fill entry credit monitor (TT-79).

Tests cover fill detection, option symbol extraction, position quantity
resolution, and the monitor's exception handling behavior.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.accounts.models import (
    InstrumentType,
    OrderLeg,
    OrderStatus,
    PlacedOrder,
)
from tastytrade.accounts.orchestrator import (
    extract_option_symbols,
    monitor_fills_for_entry_credits,
    resolve_position_quantities,
)
from tastytrade.accounts.transactions import EntryCredit


def make_order(
    status: OrderStatus = OrderStatus.FILLED,
    legs: list[OrderLeg] | None = None,
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
    )


def make_leg(
    symbol: str = "SPY  250321C00500000",
    instrument_type: InstrumentType = InstrumentType.EQUITY_OPTION,
) -> OrderLeg:
    """Create a minimal OrderLeg for testing."""
    return OrderLeg.model_construct(
        instrument_type=instrument_type,
        symbol=symbol,
        action="Buy to Open",
        quantity=1.0,
        remaining_quantity=0.0,
        fills=[],
    )


# === extract_option_symbols tests ===


class TestExtractOptionSymbols:
    def test_extracts_equity_option_symbols(self) -> None:
        order = make_order(
            legs=[
                make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION),
                make_leg("SPY  250321P00490000", InstrumentType.EQUITY_OPTION),
            ]
        )
        result = extract_option_symbols(order)
        assert set(result) == {"SPY  250321C00500000", "SPY  250321P00490000"}

    def test_extracts_future_option_symbols(self) -> None:
        order = make_order(
            legs=[
                make_leg("./6EH5 EUH5 250321C1100", InstrumentType.FUTURE_OPTION),
            ]
        )
        result = extract_option_symbols(order)
        assert result == ["./6EH5 EUH5 250321C1100"]

    def test_skips_non_option_legs(self) -> None:
        order = make_order(
            legs=[
                make_leg("AAPL", InstrumentType.EQUITY),
                make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION),
                make_leg("/ESH5", InstrumentType.FUTURE),
            ]
        )
        result = extract_option_symbols(order)
        assert result == ["SPY  250321C00500000"]

    def test_deduplicates_symbols(self) -> None:
        order = make_order(
            legs=[
                make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION),
                make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION),
            ]
        )
        result = extract_option_symbols(order)
        assert result == ["SPY  250321C00500000"]

    def test_returns_empty_for_no_option_legs(self) -> None:
        order = make_order(
            legs=[
                make_leg("AAPL", InstrumentType.EQUITY),
            ]
        )
        result = extract_option_symbols(order)
        assert result == []

    def test_mixed_equity_and_future_options(self) -> None:
        order = make_order(
            legs=[
                make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION),
                make_leg("./6EH5 EUH5 250321C1100", InstrumentType.FUTURE_OPTION),
            ]
        )
        result = extract_option_symbols(order)
        assert set(result) == {
            "SPY  250321C00500000",
            "./6EH5 EUH5 250321C1100",
        }


# === resolve_position_quantities tests ===


class TestResolvePositionQuantities:
    @pytest.mark.asyncio
    async def test_returns_positions_with_nonzero_qty(self) -> None:
        redis_client = AsyncMock()
        position_json = (
            '{"symbol": "SPY  250321C00500000", "quantity": 5.0, '
            '"quantity-direction": "Long", "instrument-type": "Equity Option", '
            '"account-number": "TEST123"}'
        )
        redis_client.hget.return_value = position_json.encode()

        result = await resolve_position_quantities(
            redis_client, ["SPY  250321C00500000"], "tastytrade:positions"
        )
        assert result == {"SPY  250321C00500000": 5}

    @pytest.mark.asyncio
    async def test_skips_missing_positions(self) -> None:
        redis_client = AsyncMock()
        redis_client.hget.return_value = None

        result = await resolve_position_quantities(
            redis_client, ["MISSING_SYMBOL"], "tastytrade:positions"
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_skips_zero_quantity_positions(self) -> None:
        redis_client = AsyncMock()
        position_json = (
            '{"symbol": "SPY  250321C00500000", "quantity": 0.0, '
            '"quantity-direction": "Long", "instrument-type": "Equity Option", '
            '"account-number": "TEST123"}'
        )
        redis_client.hget.return_value = position_json.encode()

        result = await resolve_position_quantities(
            redis_client, ["SPY  250321C00500000"], "tastytrade:positions"
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_negative_quantity(self) -> None:
        redis_client = AsyncMock()
        position_json = (
            '{"symbol": "SPY  250321C00500000", "quantity": -3.0, '
            '"quantity-direction": "Short", "instrument-type": "Equity Option", '
            '"account-number": "TEST123"}'
        )
        redis_client.hget.return_value = position_json.encode()

        result = await resolve_position_quantities(
            redis_client, ["SPY  250321C00500000"], "tastytrade:positions"
        )
        assert result == {"SPY  250321C00500000": 3}


# === monitor_fills_for_entry_credits tests ===


def make_pubsub_message(order: PlacedOrder) -> dict[str, object]:
    """Create a Redis pub/sub message dict from a PlacedOrder."""
    return {
        "type": "message",
        "data": order.model_dump_json(by_alias=True),
    }


class TestMonitorFillsForEntryCredits:
    @pytest.mark.asyncio
    async def test_filled_order_with_option_legs_triggers_recomputation(self) -> None:
        """AC1: Entry credits update on fill."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION)],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    {"type": "subscribe", "data": 1},
                    make_pubsub_message(order),
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        position_json = (
            '{"symbol": "SPY  250321C00500000", "quantity": 2.0, '
            '"quantity-direction": "Long", "instrument-type": "Equity Option", '
            '"account-number": "TEST123"}'
        )
        redis_client.hget.return_value = position_json.encode()

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        session = AsyncMock()

        entry_credit = EntryCredit(
            value=Decimal("150.00"),
            method="transaction_lifo",
            transaction_count=3,
        )

        with (
            patch(
                "tastytrade.accounts.orchestrator.TransactionsClient"
            ) as mock_txn_cls,
            patch(
                "tastytrade.accounts.orchestrator.compute_entry_credits_for_positions"
            ) as mock_compute,
        ):
            mock_txn = AsyncMock()
            mock_txn.get_transactions.return_value = []
            mock_txn_cls.return_value = mock_txn
            mock_compute.return_value = {"SPY  250321C00500000": entry_credit}

            await run_monitor_briefly(redis_client, session, publisher)

            mock_txn.get_transactions.assert_called_once_with("ACCT123")
            mock_compute.assert_called_once()
            publisher.publish_entry_credits.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_filled_order_is_ignored(self) -> None:
        """Orders with status != FILLED should not trigger processing."""
        for status in [OrderStatus.ROUTED, OrderStatus.LIVE, OrderStatus.CANCELLED]:
            order = make_order(
                status=status,
                legs=[make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION)],
            )

            pubsub_mock = AsyncMock()
            pubsub_mock.listen = MagicMock(
                return_value=_async_iter(
                    [
                        make_pubsub_message(order),
                    ]
                )
            )

            redis_client = AsyncMock()
            redis_client.pubsub = MagicMock(return_value=pubsub_mock)

            publisher = AsyncMock()
            publisher.ORDER_CHANNEL = "tastytrade:events:Order"
            publisher.POSITIONS_KEY = "tastytrade:positions"

            await run_monitor_briefly(redis_client, AsyncMock(), publisher)

            publisher.publish_entry_credits.assert_not_called()
            publisher.remove_entry_credit.assert_not_called()

    @pytest.mark.asyncio
    async def test_order_with_no_option_legs_is_ignored(self) -> None:
        """Filled orders with only equity/futures legs should not trigger."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[
                make_leg("AAPL", InstrumentType.EQUITY),
                make_leg("/ESH5", InstrumentType.FUTURE),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    make_pubsub_message(order),
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        await run_monitor_briefly(redis_client, AsyncMock(), publisher)

        publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_closed_position_cleanup(self) -> None:
        """AC3: Closed positions (qty=0) have entry credits removed."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION)],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    make_pubsub_message(order),
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)
        redis_client.hget.return_value = None

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        await run_monitor_briefly(redis_client, AsyncMock(), publisher)

        publisher.remove_entry_credit.assert_called_once_with("SPY  250321C00500000")
        publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_fill_processes_only_option_legs(self) -> None:
        """Orders with both option and non-option legs process only options."""
        order = make_order(
            status=OrderStatus.FILLED,
            legs=[
                make_leg("AAPL", InstrumentType.EQUITY),
                make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION),
            ],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    make_pubsub_message(order),
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)
        redis_client.hget.return_value = None

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        await run_monitor_briefly(redis_client, AsyncMock(), publisher)

        publisher.remove_entry_credit.assert_called_once_with("SPY  250321C00500000")

    @pytest.mark.asyncio
    async def test_malformed_message_is_logged_and_skipped(self) -> None:
        """ValidationError on bad payload should not crash the monitor."""
        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    {"type": "message", "data": b"not valid json"},
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        await run_monitor_briefly(redis_client, AsyncMock(), publisher)

        publisher.publish_entry_credits.assert_not_called()
        publisher.remove_entry_credit.assert_not_called()

    @pytest.mark.asyncio
    async def test_network_error_on_transaction_fetch_is_non_fatal(self) -> None:
        """aiohttp.ClientError during transaction fetch should not crash."""
        import aiohttp

        order = make_order(
            status=OrderStatus.FILLED,
            legs=[make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION)],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    make_pubsub_message(order),
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        position_json = (
            '{"symbol": "SPY  250321C00500000", "quantity": 2.0, '
            '"quantity-direction": "Long", "instrument-type": "Equity Option", '
            '"account-number": "TEST123"}'
        )
        redis_client.hget.return_value = position_json.encode()

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        with patch(
            "tastytrade.accounts.orchestrator.TransactionsClient"
        ) as mock_txn_cls:
            mock_txn = AsyncMock()
            mock_txn.get_transactions.side_effect = aiohttp.ClientError("network error")
            mock_txn_cls.return_value = mock_txn

            await run_monitor_briefly(redis_client, AsyncMock(), publisher)

        publisher.publish_entry_credits.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_expiry_is_non_fatal(self) -> None:
        """AsyncUnauthorizedError (401) should not crash the monitor."""
        from tastytrade.common.exceptions import AsyncUnauthorizedError

        order = make_order(
            status=OrderStatus.FILLED,
            legs=[make_leg("SPY  250321C00500000", InstrumentType.EQUITY_OPTION)],
        )

        pubsub_mock = AsyncMock()
        pubsub_mock.listen = MagicMock(
            return_value=_async_iter(
                [
                    make_pubsub_message(order),
                ]
            )
        )

        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=pubsub_mock)

        position_json = (
            '{"symbol": "SPY  250321C00500000", "quantity": 2.0, '
            '"quantity-direction": "Long", "instrument-type": "Equity Option", '
            '"account-number": "TEST123"}'
        )
        redis_client.hget.return_value = position_json.encode()

        publisher = AsyncMock()
        publisher.ORDER_CHANNEL = "tastytrade:events:Order"
        publisher.POSITIONS_KEY = "tastytrade:positions"

        session = AsyncMock()

        with patch(
            "tastytrade.accounts.orchestrator.TransactionsClient"
        ) as mock_txn_cls:
            mock_txn = AsyncMock()
            mock_txn.get_transactions.side_effect = AsyncUnauthorizedError()
            mock_txn_cls.return_value = mock_txn

            await run_monitor_briefly(redis_client, session, publisher)

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

        await run_monitor_briefly(redis_client, AsyncMock(), publisher)

        publisher.publish_entry_credits.assert_not_called()


# === Helpers ===


async def _async_iter(items: list[dict[str, object]]):  # type: ignore[type-arg]
    """Yield items as an async iterator, then block until cancelled."""
    for item in items:
        yield item
    # Block indefinitely to keep the monitor alive until the test cancels it.
    # The monitor's finally block handles cleanup on CancelledError.
    await asyncio.get_event_loop().create_future()


async def run_monitor_briefly(
    redis_client: AsyncMock,
    session: AsyncMock,
    publisher: AsyncMock,
    timeout: float = 0.05,
) -> None:
    """Run the fill monitor and cancel it after a brief timeout."""
    task = asyncio.create_task(
        monitor_fills_for_entry_credits(redis_client, session, "ACCT123", publisher)
    )
    await asyncio.sleep(timeout)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
