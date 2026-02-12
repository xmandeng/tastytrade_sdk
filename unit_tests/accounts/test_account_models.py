"""Tests for Account, Position, and AccountBalance models (TT-28)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from pydantic import ValidationError

from tastytrade.accounts.client import AccountsClient
from tastytrade.accounts.models import (
    Account,
    AccountBalance,
    InstrumentType,
    Position,
    QuantityDirection,
    TastyTradeApiModel,
)
from tastytrade.connections.requests import AsyncSessionHandler


# ---------------------------------------------------------------------------
# Factory functions — hyphenated keys, string floats (matches real API shape)
# ---------------------------------------------------------------------------


def make_position_json(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": "AAPL",
        "instrument-type": "Equity",
        "underlying-symbol": "AAPL",
        "quantity": "100.0",
        "quantity-direction": "Long",
        "multiplier": "1",
        "close-price": "185.50",
        "average-open-price": "175.25",
        "mark": "186.00",
        "mark-price": "186.00",
        "average-daily-market-close-price": "185.00",
        "average-yearly-market-close-price": "180.00",
        "is-frozen": False,
        "is-suppressed": False,
        "restricted-quantity": "0.0",
        "cost-effect": "Debit",
        "streamer-symbol": "AAPL",
        "realized-day-gain": "0.0",
        "realized-day-gain-effect": "None",
        "realized-day-gain-date": "2026-02-01",
        "realized-today": "0.0",
        "realized-today-effect": "None",
        "realized-today-date": "2026-02-01",
        "created-at": "2026-01-15T10:30:00Z",
        "updated-at": "2026-02-01T14:00:00Z",
    }
    base.update(overrides)
    return base


def make_account_json(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "account-type-name": "Individual",
        "nickname": "My Account",
        "is-closed": False,
        "day-trader-status": False,
        "is-firm-error": False,
        "is-firm-proprietary": False,
        "is-foreign": False,
        "is-futures-approved": True,
        "is-test-drive": True,
        "investment-objective": "SPECULATION",
        "suitable-options-level": "No Restrictions",
        "margin-or-cash": "Margin",
        "ext-crm-id": "a0qTw000004X0OlIAK",
        "external-id": "Aed8732a5-5e8b-4394-8b18-50e06d22dbdd",
        "funding-date": "2024-12-10",
        "futures-account-purpose": "SPECULATING",
        "regulatory-domain": "USA",
        "opened-at": "2025-06-01T00:00:00Z",
        "created-at": "2025-06-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def make_balance_json(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "cash-balance": "25000.50",
        "net-liquidating-value": "50000.75",
        "equity-buying-power": "40000.00",
        "derivative-buying-power": "35000.00",
        "day-trading-buying-power": "100000.00",
        "effective-cryptocurrency-buying-power": "10000.00",
        "long-equity-value": "30000.00",
        "short-equity-value": "0.0",
        "long-derivative-value": "5000.00",
        "short-derivative-value": "0.0",
        "long-futures-value": "0.0",
        "short-futures-value": "0.0",
        "long-futures-derivative-value": "0.0",
        "short-futures-derivative-value": "0.0",
        "long-margineable-value": "25000.00",
        "short-margineable-value": "0.0",
        "long-bond-value": "0.0",
        "long-cryptocurrency-value": "0.0",
        "short-cryptocurrency-value": "0.0",
        "long-fixed-income-security-value": "0.0",
        "long-index-derivative-value": "0.0",
        "short-index-derivative-value": "0.0",
        "margin-equity": "50000.00",
        "maintenance-requirement": "15000.00",
        "maintenance-excess": "35000.00",
        "margin-settle-balance": "25000.00",
        "futures-margin-requirement": "0.0",
        "cryptocurrency-margin-requirement": "0.0",
        "bond-margin-requirement": "0.0",
        "equity-offering-margin-requirement": "0.0",
        "fixed-income-security-margin-requirement": "0.0",
        "futures-overnight-margin-requirement": "0.0",
        "futures-intraday-margin-requirement": "0.0",
        "pending-cash": "0.0",
        "pending-cash-effect": "None",
        "cash-available-to-withdraw": "20000.00",
        "cash-settle-balance": "25000.00",
        "closed-loop-available-balance": "20000.00",
        "available-trading-funds": "40000.00",
        "day-trade-excess": "85000.00",
        "day-trading-call-value": "0.0",
        "day-equity-call-value": "0.0",
        "reg-t-call-value": "0.0",
        "reg-t-margin-requirement": "15000.00",
        "sma-equity-option-buying-power": "40000.00",
        "special-memorandum-account-value": "40000.00",
        "special-memorandum-account-apex-adjustment": "0.0",
        "intraday-equities-cash-amount": "0.0",
        "intraday-equities-cash-effect": "None",
        "intraday-futures-cash-amount": "0.0",
        "intraday-futures-cash-effect": "None",
        "unsettled-cryptocurrency-fiat-amount": "0.0",
        "unsettled-cryptocurrency-fiat-effect": "None",
        "previous-day-cryptocurrency-fiat-amount": "0.0",
        "previous-day-cryptocurrency-fiat-effect": "None",
        "pending-margin-interest": "0.0",
        "apex-starting-day-margin-equity": "50000.00",
        "buying-power-adjustment": "0.0",
        "buying-power-adjustment-effect": "None",
        "total-pending-liquidity-pool-rebate": "0.0",
        "used-derivative-buying-power": "5000.00",
        "snapshot-date": "2026-02-01",
        "time-of-day": "EOD",
        "currency": "USD",
        "updated-at": "2026-02-01T16:00:00Z",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helper: mock AsyncSessionHandler with a canned JSON response
# ---------------------------------------------------------------------------


def mock_session(json_response: Any) -> Mock:
    """Create a Mock(spec=AsyncSessionHandler) that returns json_response."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value=json_response)
    response.headers = {"content-type": "application/json"}

    context_manager = AsyncMock()
    context_manager.__aenter__ = AsyncMock(return_value=response)
    context_manager.__aexit__ = AsyncMock(return_value=False)

    session_obj = MagicMock()
    session_obj.get = MagicMock(return_value=context_manager)

    mock = Mock(spec=AsyncSessionHandler)
    mock.session = session_obj
    mock.base_url = "https://api.tastyworks.com"
    return mock


# ---------------------------------------------------------------------------
# AC1: Position model parses hyphenated JSON
# ---------------------------------------------------------------------------


def test_position_parses_hyphenated_json() -> None:
    data = make_position_json()
    pos = Position.model_validate(data)
    assert pos.account_number == "5WT00001"
    assert pos.symbol == "AAPL"
    assert pos.instrument_type == InstrumentType.EQUITY
    assert pos.quantity_direction == QuantityDirection.LONG
    assert pos.underlying_symbol == "AAPL"


def test_position_float_coercion_from_string() -> None:
    data = make_position_json(quantity="100.0", **{"close-price": "185.50"})
    pos = Position.model_validate(data)
    assert pos.quantity == 100.0
    assert pos.close_price == 185.5
    assert isinstance(pos.quantity, float)
    assert isinstance(pos.close_price, float)


def test_position_float_handles_nan() -> None:
    data = make_position_json(**{"close-price": "NaN"})
    pos = Position.model_validate(data)
    assert pos.close_price is None


# ---------------------------------------------------------------------------
# AC2: Models are frozen and reject extra fields
# ---------------------------------------------------------------------------


def test_position_is_frozen() -> None:
    pos = Position.model_validate(make_position_json())
    with pytest.raises(ValidationError):
        pos.symbol = "MSFT"  # type: ignore[misc]


def test_position_rejects_extra_fields() -> None:
    data = make_position_json(**{"unexpected-field": "boom"})
    with pytest.raises(ValidationError):
        Position.model_validate(data)


def test_account_is_frozen() -> None:
    acct = Account.model_validate(make_account_json())
    with pytest.raises(ValidationError):
        acct.nickname = "Changed"  # type: ignore[misc]


def test_balance_is_frozen() -> None:
    bal = AccountBalance.model_validate(make_balance_json())
    with pytest.raises(ValidationError):
        bal.cash_balance = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC3: InstrumentType enum covers required types
# ---------------------------------------------------------------------------


def test_instrument_type_covers_required_types() -> None:
    required = {"Equity", "Equity Option", "Future", "Future Option", "Cryptocurrency"}
    actual = {member.value for member in InstrumentType}
    assert required.issubset(actual)


def test_instrument_type_from_api_string() -> None:
    assert InstrumentType("Equity") == InstrumentType.EQUITY
    assert InstrumentType("Equity Option") == InstrumentType.EQUITY_OPTION
    assert InstrumentType("Cryptocurrency") == InstrumentType.CRYPTOCURRENCY


def test_quantity_direction_values() -> None:
    assert QuantityDirection("Long") == QuantityDirection.LONG
    assert QuantityDirection("Short") == QuantityDirection.SHORT
    assert QuantityDirection("Zero") == QuantityDirection.ZERO


def test_unknown_instrument_type_fallback() -> None:
    data = make_position_json(**{"instrument-type": "NewFancyType"})
    pos = Position.model_validate(data)
    assert pos.instrument_type == InstrumentType.UNKNOWN


# ---------------------------------------------------------------------------
# AC4: AccountsClient.get_positions()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_positions_returns_typed_list() -> None:
    session = mock_session({"data": {"items": [make_position_json()]}})
    client = AccountsClient(session)
    positions = await client.get_positions("5WT00001")
    assert isinstance(positions, list)
    assert len(positions) == 1
    assert isinstance(positions[0], Position)
    assert positions[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_get_positions_empty_list() -> None:
    session = mock_session({"data": {"items": []}})
    client = AccountsClient(session)
    positions = await client.get_positions("5WT00001")
    assert positions == []


@pytest.mark.asyncio
async def test_get_positions_option_position() -> None:
    option_data = make_position_json(
        symbol="AAPL  260220C00185000",
        **{
            "instrument-type": "Equity Option",
            "underlying-symbol": "AAPL",
            "streamer-symbol": ".AAPL260220C185",
            "multiplier": "100",
            "expires-at": "2026-02-20T21:00:00Z",
        },
    )
    session = mock_session({"data": {"items": [option_data]}})
    client = AccountsClient(session)
    positions = await client.get_positions("5WT00001")
    assert positions[0].instrument_type == InstrumentType.EQUITY_OPTION
    assert positions[0].multiplier == 100.0
    assert positions[0].streamer_symbol == ".AAPL260220C185"


# ---------------------------------------------------------------------------
# AC5: AccountsClient.get_accounts()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_accounts_returns_typed_list() -> None:
    session = mock_session({"data": {"items": [{"account": make_account_json()}]}})
    client = AccountsClient(session)
    accounts = await client.get_accounts()
    assert isinstance(accounts, list)
    assert len(accounts) == 1
    assert isinstance(accounts[0], Account)
    assert accounts[0].account_number == "5WT00001"
    assert accounts[0].account_type_name == "Individual"


# ---------------------------------------------------------------------------
# AC6: AccountsClient.get_balances()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_balances_returns_typed_object() -> None:
    session = mock_session({"data": make_balance_json()})
    client = AccountsClient(session)
    balance = await client.get_balances("5WT00001")
    assert isinstance(balance, AccountBalance)
    assert balance.account_number == "5WT00001"
    assert balance.net_liquidating_value == 50000.75


def test_balance_float_coercion() -> None:
    bal = AccountBalance.model_validate(make_balance_json())
    assert bal.cash_balance == 25000.5
    assert isinstance(bal.cash_balance, float)
    assert bal.equity_buying_power == 40000.0


# ---------------------------------------------------------------------------
# AC7: Position includes streamer_symbol
# ---------------------------------------------------------------------------


def test_position_includes_streamer_symbol() -> None:
    pos = Position.model_validate(make_position_json())
    assert pos.streamer_symbol == "AAPL"


def test_position_streamer_symbol_optional() -> None:
    data = make_position_json()
    del data["streamer-symbol"]
    pos = Position.model_validate(data)
    assert pos.streamer_symbol is None


# ---------------------------------------------------------------------------
# AC8: Account config — Credentials loads account number
# ---------------------------------------------------------------------------


def test_credentials_loads_sandbox_account() -> None:
    config = MagicMock()
    config.get = MagicMock(
        side_effect=lambda key: {
            "TT_SANDBOX_URL": "https://sandbox.tastyworks.com",
            "TT_SANDBOX_ACCOUNT": "5WT00001",
            "TT_SANDBOX_USER": "sandbox_user",
            "TT_SANDBOX_PASS": "sandbox_pass",
        }[key]
    )
    from tastytrade.connections import Credentials

    creds = Credentials(config=config, env="Test")
    assert creds.account_number == "5WT00001"
    assert creds.login == "sandbox_user"
    assert creds.password == "sandbox_pass"
    assert creds.oauth_client_id is None


def test_credentials_loads_live_account() -> None:
    config = MagicMock()
    config.get = MagicMock(
        side_effect=lambda key: {
            "TT_API_URL": "https://api.tastyworks.com",
            "TT_ACCOUNT": "ABC12345",
            "TT_OAUTH_CLIENT_ID": "test-client-id",
            "TT_OAUTH_CLIENT_SECRET": "test-client-secret",
            "TT_OAUTH_REFRESH_TOKEN": "test-refresh-token",
        }[key]
    )
    from tastytrade.connections import Credentials

    creds = Credentials(config=config, env="Live")
    assert creds.account_number == "ABC12345"


# ---------------------------------------------------------------------------
# Account validation — fail fast on misconfigured account numbers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_account_number_succeeds() -> None:
    session = mock_session({"data": {"items": [{"account": make_account_json()}]}})
    client = AccountsClient(session)
    await client.validate_account_number("5WT00001")  # should not raise


@pytest.mark.asyncio
async def test_validate_account_number_rejects_unknown() -> None:
    session = mock_session({"data": {"items": [{"account": make_account_json()}]}})
    client = AccountsClient(session)
    with pytest.raises(ValueError, match="not found in authenticated session"):
        await client.validate_account_number("WRONG123")


@pytest.mark.asyncio
async def test_validate_account_number_rejects_empty() -> None:
    session = mock_session({"data": {"items": [{"account": make_account_json()}]}})
    client = AccountsClient(session)
    with pytest.raises(ValueError, match="must not be empty"):
        await client.validate_account_number("")


# ---------------------------------------------------------------------------
# Base model sanity
# ---------------------------------------------------------------------------


def test_tastytrade_api_model_config() -> None:
    config = TastyTradeApiModel.model_config
    assert config["frozen"] is True
    assert config["extra"] == "forbid"
    assert config["populate_by_name"] is True
