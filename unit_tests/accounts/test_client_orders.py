"""Unit tests for AccountsClient.get_orders() pagination."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.accounts.client import AccountsClient
from tastytrade.accounts.models import PlacedOrder


def make_order_item(order_id: int) -> dict:
    """Minimal valid order dict matching PlacedOrder schema."""
    return {
        "id": order_id,
        "account-number": "ACCT123",
        "order-type": "Limit",
        "time-in-force": "Day",
        "status": "Filled",
        "legs": [],
    }


def make_response(items: list[dict], total_pages: int = 1) -> AsyncMock:
    """Build a mock aiohttp response context manager."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "data": {"items": items},
            "pagination": {"total-pages": total_pages},
        }
    )
    return response


def make_session(responses: list[AsyncMock]) -> MagicMock:
    """Build a mock AsyncSessionHandler with queued responses."""
    session = MagicMock()
    session.base_url = "https://api.tastyworks.com"
    ctx_managers = []
    for resp in responses:
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx_managers.append(ctx)
    session.session.get = MagicMock(side_effect=ctx_managers)
    return session


class TestGetOrders:
    @pytest.mark.asyncio
    async def test_single_page(self) -> None:
        """Fetches all orders from a single-page response."""
        items = [make_order_item(1), make_order_item(2)]
        resp = make_response(items, total_pages=1)
        session = make_session([resp])
        client = AccountsClient(session)

        orders = await client.get_orders("ACCT123")

        assert len(orders) == 2
        assert all(isinstance(o, PlacedOrder) for o in orders)
        assert orders[0].id == 1
        assert orders[1].id == 2

    @pytest.mark.asyncio
    async def test_multi_page(self) -> None:
        """Paginates across multiple pages."""
        page1 = make_response([make_order_item(1)], total_pages=2)
        page2 = make_response([make_order_item(2)], total_pages=2)
        session = make_session([page1, page2])
        client = AccountsClient(session)

        orders = await client.get_orders("ACCT123")

        assert len(orders) == 2
        assert orders[0].id == 1
        assert orders[1].id == 2
        assert session.session.get.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        """Returns empty list when no orders exist."""
        resp = make_response([], total_pages=1)
        session = make_session([resp])
        client = AccountsClient(session)

        orders = await client.get_orders("ACCT123")

        assert orders == []

    @pytest.mark.asyncio
    async def test_date_params_passed(self) -> None:
        """Start/end date filters are passed as query params."""
        resp = make_response([], total_pages=1)
        session = make_session([resp])
        client = AccountsClient(session)

        await client.get_orders(
            "ACCT123", start_date="2025-01-01", end_date="2025-03-01"
        )

        call_kwargs = session.session.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["start-date"] == "2025-01-01"
        assert params["end-date"] == "2025-03-01"
        assert params["sort"] == "Desc"

    @pytest.mark.asyncio
    async def test_no_pagination_key(self) -> None:
        """Handles responses without pagination metadata (defaults to 1 page)."""
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(
            return_value={"data": {"items": [make_order_item(1)]}}
        )
        session = make_session([response])
        client = AccountsClient(session)

        orders = await client.get_orders("ACCT123")

        assert len(orders) == 1
