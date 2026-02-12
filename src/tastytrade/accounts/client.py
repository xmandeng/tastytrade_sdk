import logging

from tastytrade.accounts.models import Account, AccountBalance, Position
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
                f"Account {account_number!r} not found in authenticated session. "
                f"Valid accounts: {valid_numbers}"
            )
        logger.info(
            "Account %s validated against %d accounts", account_number, len(accounts)
        )

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
            logger.info(
                "Fetched %d positions for account %s", len(positions), account_number
            )
            return positions

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
            logger.info(
                "Fetched balances for account %s — net_liq=%.2f, cash=%.2f",
                account_number,
                balance.net_liquidating_value or 0.0,
                balance.cash_balance or 0.0,
            )
            return balance
