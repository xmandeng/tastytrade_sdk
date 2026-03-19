import logging
from typing import Optional

from tastytrade.accounts.models import Account, AccountBalance, PlacedOrder, Position
from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.utils.validators import validate_async_response

logger = logging.getLogger(__name__)


class AccountsClient:
    def __init__(self, session: AsyncSessionHandler) -> None:
        self.session = session

    async def validate_account_number(self, account_number: str) -> None:
        """Validate that an account number belongs to the authenticated session.

        Raises ValueError if the account number is empty or not found
        in the accounts returned by the API.
        """
        if not account_number:
            raise ValueError("Account number must not be empty")

        accounts = await self.get_accounts()
        valid_numbers = [a.account_number for a in accounts]

        if account_number not in valid_numbers:
            raise ValueError(
                f"Account ending in ...{account_number[-4:]} not found in "
                f"authenticated session ({len(valid_numbers)} accounts available)"
            )
        logger.info("Account validated against %d accounts", len(accounts))

    async def get_accounts(self) -> list[Account]:
        """Fetch all accounts for the authenticated customer.

        API shape: GET /customers/me/accounts
        Response: {"data": {"items": [{"account": {...}}, ...]}}
        """
        async with self.session.session.get(
            f"{self.session.base_url}/customers/me/accounts"
        ) as response:
            await validate_async_response(response)
            data = await response.json()
            items = data["data"]["items"]
            accounts = [Account.model_validate(item["account"]) for item in items]
            logger.info("Fetched %d accounts", len(accounts))
            return accounts

    async def get_positions(self, account_number: str) -> list[Position]:
        """Fetch positions for a specific account.

        API shape: GET /accounts/{account_number}/positions
        Response: {"data": {"items": [...]}}
        """
        async with self.session.session.get(
            f"{self.session.base_url}/accounts/{account_number}/positions"
        ) as response:
            await validate_async_response(response)
            data = await response.json()
            items = data["data"]["items"]
            positions = [Position.model_validate(item) for item in items]
            logger.info("Fetched %d positions", len(positions))
            return positions

    async def get_orders(
        self,
        account_number: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        per_page: int = 250,
    ) -> list[PlacedOrder]:
        """Fetch orders for an account with pagination.

        API shape: GET /accounts/{account_number}/orders
        Response: {"data": {"items": [...]}, "pagination": {"total-pages": N}}

        Args:
            account_number: The account to query.
            start_date: Optional start date filter (YYYY-MM-DD).
            end_date: Optional end date filter (YYYY-MM-DD).
            per_page: Page size for pagination.

        Returns:
            All orders across all pages, newest first.
        """
        all_orders: list[PlacedOrder] = []
        page_offset = 0

        while True:
            params: dict[str, str | int] = {
                "per-page": per_page,
                "page-offset": page_offset,
                "sort": "Desc",
            }
            if start_date:
                params["start-date"] = start_date
            if end_date:
                params["end-date"] = end_date

            async with self.session.session.get(
                f"{self.session.base_url}/accounts/{account_number}/orders",
                params=params,
            ) as response:
                await validate_async_response(response)
                data = await response.json()

            items = data["data"]["items"]
            for item in items:
                all_orders.append(PlacedOrder.model_validate(item))

            pagination = data.get("pagination", {})
            total_pages = pagination.get("total-pages", 1)
            page_offset += 1

            if page_offset >= total_pages:
                break

        logger.info("Fetched %d orders", len(all_orders))
        return all_orders

    async def get_balances(self, account_number: str) -> AccountBalance:
        """Fetch balances for a specific account.

        API shape: GET /accounts/{account_number}/balances
        Response: {"data": {...}} (single object)
        """
        async with self.session.session.get(
            f"{self.session.base_url}/accounts/{account_number}/balances"
        ) as response:
            await validate_async_response(response)
            data = await response.json()
            balance = AccountBalance.model_validate(data["data"])
            logger.info("Fetched balances")
            return balance
