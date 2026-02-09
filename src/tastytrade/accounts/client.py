import logging

from tastytrade.accounts.models import Account, AccountBalance, Position
from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.utils.validators import validate_async_response

logger = logging.getLogger(__name__)


class AccountsClient:
    def __init__(self, session: AsyncSessionHandler) -> None:
        self.session = session

    async def get_accounts(self) -> list[Account]:
        """Fetch all accounts for the authenticated customer.

        API shape: GET /customers/me/accounts
        Response: {"data": {"items": [{"account": {...}}, ...]}}
        """
        async with self.session.session.get(
            f"{self.session.base_url}/customers/me/accounts"
        ) as response:
            validate_async_response(response)
            data = await response.json()
            items = data["data"]["items"]
            return [Account.model_validate(item["account"]) for item in items]

    async def get_positions(self, account_number: str) -> list[Position]:
        """Fetch positions for a specific account.

        API shape: GET /accounts/{account_number}/positions
        Response: {"data": {"items": [...]}}
        """
        async with self.session.session.get(
            f"{self.session.base_url}/accounts/{account_number}/positions"
        ) as response:
            validate_async_response(response)
            data = await response.json()
            items = data["data"]["items"]
            return [Position.model_validate(item) for item in items]

    async def get_balances(self, account_number: str) -> AccountBalance:
        """Fetch balances for a specific account.

        API shape: GET /accounts/{account_number}/balances
        Response: {"data": {...}} (single object)
        """
        async with self.session.session.get(
            f"{self.session.base_url}/accounts/{account_number}/balances"
        ) as response:
            validate_async_response(response)
            data = await response.json()
            return AccountBalance.model_validate(data["data"])
