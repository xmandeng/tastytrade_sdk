"""Tests for Account, Position, and AccountBalance models (TT-28, TT-83)."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from pydantic import ValidationError

from tastytrade.accounts.client import AccountsClient
from tastytrade.accounts.models import (
    Account,
    AccountBalance,
    InstrumentType,
    PlacedComplexOrder,
    PlacedOrder,
    Position,
    QuantityDirection,
    TastyTradeApiModel,
    TradeChain,
)
from tastytrade.accounts.transactions import EntryCredit
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


def test_position_preserves_extra_fields() -> None:
    data = make_position_json(**{"update-type": "Close Price"})
    pos = Position.model_validate(data)
    assert pos.symbol == data["symbol"]
    assert pos.model_extra is not None
    assert pos.model_extra["update-type"] == "Close Price"


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
    assert config["extra"] == "allow"
    assert config["populate_by_name"] is True


# ---------------------------------------------------------------------------
# TT-83: eventSymbol property tests
# ---------------------------------------------------------------------------


class TestEventSymbol:
    def test_position_returns_streamer_symbol(self) -> None:
        pos = Position.model_validate(
            make_position_json(**{"streamer-symbol": ".AAPL260220C185"})
        )
        assert pos.eventSymbol == ".AAPL260220C185"

    def test_position_falls_back_to_symbol(self) -> None:
        data = make_position_json()
        del data["streamer-symbol"]
        pos = Position.model_validate(data)
        assert pos.eventSymbol == "AAPL"

    def test_placed_order_returns_underlying(self) -> None:
        order = PlacedOrder.model_validate(
            {
                "id": 1,
                "account-number": "TEST",
                "order-type": "Limit",
                "time-in-force": "Day",
                "status": "Filled",
                "underlying-symbol": "SPY",
                "legs": [],
            }
        )
        assert order.eventSymbol == "SPY"

    def test_placed_order_returns_empty_without_underlying(self) -> None:
        order = PlacedOrder.model_validate(
            {
                "id": 1,
                "account-number": "TEST",
                "order-type": "Limit",
                "time-in-force": "Day",
                "status": "Filled",
                "legs": [],
            }
        )
        assert order.eventSymbol == ""

    def test_complex_order_returns_child_underlying(self) -> None:
        order = PlacedComplexOrder.model_validate(
            {
                "id": 1,
                "account-number": "TEST",
                "type": "OCO",
                "orders": [
                    {
                        "id": 2,
                        "account-number": "TEST",
                        "order-type": "Limit",
                        "time-in-force": "Day",
                        "status": "Filled",
                        "underlying-symbol": "AAPL",
                        "legs": [],
                    }
                ],
            }
        )
        assert order.eventSymbol == "AAPL"

    def test_complex_order_returns_empty_without_orders(self) -> None:
        order = PlacedComplexOrder.model_validate(
            {
                "id": 1,
                "account-number": "TEST",
                "type": "OCO",
                "orders": [],
            }
        )
        assert order.eventSymbol == ""

    def test_trade_chain_returns_underlying(self) -> None:
        chain = TradeChain.model_validate(
            {
                "id": "chain-1",
                "description": "Iron Condor",
                "underlying-symbol": "SPY",
                "computed-data": {"open": True},
                "lite-nodes": [],
            }
        )
        assert chain.eventSymbol == "SPY"

    def test_entry_credit_returns_symbol(self) -> None:
        credit = EntryCredit(
            symbol=".AAPL260220C185",
            value=Decimal("100"),
            transaction_count=3,
        )
        assert credit.eventSymbol == ".AAPL260220C185"


# ---------------------------------------------------------------------------
# TT-83: InfluxMixin.for_influx() tests
# ---------------------------------------------------------------------------


class TestForInflux:
    def test_scalar_passthrough(self) -> None:
        """int/float/str/bool values pass through unchanged."""
        pos = Position.model_validate(make_position_json())
        ns = pos.for_influx()
        assert ns.quantity == 100.0
        assert ns.symbol == "AAPL"
        assert isinstance(ns.quantity, float)

    def test_event_symbol_attached(self) -> None:
        """Namespace has eventSymbol from the model property."""
        pos = Position.model_validate(make_position_json())
        ns = pos.for_influx()
        assert ns.eventSymbol == "AAPL"

    def test_class_name_preserved(self) -> None:
        """ns.__class__.__name__ matches the original model for InfluxDB measurement."""
        pos = Position.model_validate(make_position_json())
        ns = pos.for_influx()
        assert ns.__class__.__name__ == "Position"

    def test_json_field_serialization(self) -> None:
        """Fields in INFLUX_JSON_FIELDS are serialized to JSON strings."""
        import json

        order = PlacedOrder.model_validate(
            {
                "id": 1,
                "account-number": "TEST",
                "order-type": "Limit",
                "time-in-force": "Day",
                "status": "Filled",
                "underlying-symbol": "SPY",
                "legs": [
                    {
                        "instrument-type": "Equity Option",
                        "symbol": "SPY  250321C00500000",
                        "action": "Buy to Open",
                        "quantity": "1",
                        "fills": [],
                    }
                ],
            }
        )
        ns = order.for_influx()
        # legs should be a JSON string, not a list
        assert isinstance(ns.legs, str)
        parsed = json.loads(ns.legs)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_position_no_json_fields(self) -> None:
        """Position has no INFLUX_JSON_FIELDS — all fields pass through natively."""
        pos = Position.model_validate(make_position_json())
        ns = pos.for_influx()
        # No fields should be JSON strings (except enum values which are str)
        assert not isinstance(ns.quantity, str)
        assert isinstance(ns.account_number, str)

    def test_influx_exclude_removes_fields(self) -> None:
        """Fields in INFLUX_EXCLUDE are not in the namespace."""
        pos = Position.model_validate(make_position_json())
        # Position has empty exclude by default, manually test the mechanism
        original_exclude = Position.INFLUX_EXCLUDE
        try:
            Position.INFLUX_EXCLUDE = {"symbol"}
            ns = pos.for_influx()
            assert not hasattr(ns, "symbol")
        finally:
            Position.INFLUX_EXCLUDE = original_exclude

    def test_unknown_non_scalar_defaults_to_json(self) -> None:
        """Unexpected nested fields from extra='allow' are JSON-serialized."""
        import json

        data = make_position_json(**{"nested-data": {"key": "value"}})
        pos = Position.model_validate(data)
        ns = pos.for_influx()
        # The extra field should be JSON-serialized since it's a dict
        extra_val = getattr(ns, "nested-data")
        assert isinstance(extra_val, str)
        parsed = json.loads(extra_val)
        assert parsed == {"key": "value"}

    def test_frozen_model_property_compatibility(self) -> None:
        """@property eventSymbol works on frozen models without mutation."""
        pos = Position.model_validate(make_position_json())
        # Model is frozen — eventSymbol is read-only property
        ns = pos.for_influx()
        assert ns.eventSymbol == pos.eventSymbol

    def test_trade_chain_json_fields(self) -> None:
        """TradeChain serializes computed_data and lite_nodes as JSON."""
        import json

        chain = TradeChain.model_validate(
            {
                "id": "chain-1",
                "description": "Iron Condor",
                "underlying-symbol": "SPY",
                "computed-data": {"open": True, "total-fees": "2.50"},
                "lite-nodes": [],
            }
        )
        ns = chain.for_influx()
        assert ns.__class__.__name__ == "TradeChain"
        assert ns.eventSymbol == "SPY"
        # computed_data is a Pydantic model — should be model_dump_json
        assert isinstance(ns.computed_data, str)
        parsed = json.loads(ns.computed_data)
        assert parsed["open"] is True

    def test_entry_credit_for_influx(self) -> None:
        """EntryCredit for_influx produces correct namespace."""
        credit = EntryCredit(
            symbol=".AAPL260220C185",
            value=Decimal("150"),
            method="transaction_lifo",
            transaction_count=3,
        )
        ns = credit.for_influx()
        assert ns.__class__.__name__ == "EntryCredit"
        assert ns.eventSymbol == ".AAPL260220C185"
        assert ns.method == "transaction_lifo"

    def test_datetime_serialized_to_isoformat(self) -> None:
        """datetime fields are converted to ISO strings for InfluxDB compatibility."""
        data = make_position_json(**{"created-at": "2026-03-07T15:30:00+00:00"})
        pos = Position.model_validate(data)
        ns = pos.for_influx()
        assert isinstance(ns.created_at, str)
        assert "2026-03-07" in ns.created_at

    def test_enum_serialized_to_value(self) -> None:
        """Enum fields are converted to their string values."""
        pos = Position.model_validate(make_position_json())
        ns = pos.for_influx()
        # instrument_type is an Enum field
        assert ns.instrument_type == "Equity"
        assert isinstance(ns.instrument_type, str)
