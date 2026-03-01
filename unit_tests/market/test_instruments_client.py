"""Tests for InstrumentsClient and instrument models."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tastytrade.market.instruments import INSTRUMENT_BATCH_SIZE, InstrumentsClient
from tastytrade.market.models import (
    CryptocurrencyInstrument,
    EquityInstrument,
    EquityOptionInstrument,
    FutureInstrument,
    FutureOptionInstrument,
    OptionType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_ok_response(json_data: dict[str, Any]) -> AsyncMock:
    """Create a mock aiohttp response with status=200 and given JSON payload."""
    response_mock = AsyncMock()
    response_mock.status = 200
    response_mock.json.return_value = json_data
    response_mock.__aenter__ = AsyncMock(return_value=response_mock)
    response_mock.__aexit__ = AsyncMock(return_value=False)
    return response_mock


def make_equity_option_json(**overrides: Any) -> dict[str, Any]:
    """Factory for equity option instrument API response."""
    base: dict[str, Any] = {
        "symbol": "SPY   260320C00500000",
        "instrument-type": "Equity Option",
        "strike-price": "500.0",
        "option-type": "C",
        "root-symbol": "SPY",
        "underlying-symbol": "SPY",
        "expiration-date": "2026-03-20",
        "days-to-expiration": 20,
        "expires-at": "2026-03-20T21:00:00Z",
        "exercise-style": "American",
        "settlement-type": "PM",
        "shares-per-contract": 100,
        "streamer-symbol": ".SPY260320C500",
        "active": True,
        "is-closing-only": False,
    }
    base.update(overrides)
    return base


def make_future_option_json(**overrides: Any) -> dict[str, Any]:
    """Factory for future option instrument API response."""
    base: dict[str, Any] = {
        "symbol": "./MESM6EX3H6 260320P6450",
        "underlying-symbol": "/MESM6",
        "product-code": "EX3",
        "expiration-date": "2026-03-20",
        "strike-price": "6450.0",
        "option-type": "P",
        "exchange": "CME",
        "streamer-symbol": "./EX3H26P6450:XCME",
    }
    base.update(overrides)
    return base


def make_equity_json(**overrides: Any) -> dict[str, Any]:
    """Factory for equity instrument API response."""
    base: dict[str, Any] = {
        "symbol": "SPY",
        "instrument-type": "Equity",
        "description": "SPDR S&P 500 ETF Trust",
        "is-etf": True,
        "active": True,
    }
    base.update(overrides)
    return base


def make_future_json(**overrides: Any) -> dict[str, Any]:
    """Factory for future instrument API response."""
    base: dict[str, Any] = {
        "symbol": "/MESM6",
        "product-code": "MES",
        "contract-size": "5.0",
        "notional-multiplier": "5.0",
        "expiration-date": "2026-06-19",
        "active": True,
    }
    base.update(overrides)
    return base


def make_crypto_json(**overrides: Any) -> dict[str, Any]:
    """Factory for cryptocurrency instrument API response."""
    base: dict[str, Any] = {
        "symbol": "BTC/USD",
        "instrument-type": "Cryptocurrency",
        "description": "Bitcoin",
        "active": True,
    }
    base.update(overrides)
    return base


def make_api_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap items in TT API response shape."""
    return {"data": {"items": items}}


@pytest.fixture
def mock_session() -> MagicMock:
    """Mock AsyncSessionHandler with controllable responses."""
    session = MagicMock()
    session.base_url = "https://api.tastyworks.com"
    session.session = MagicMock()
    return session


@pytest.fixture
def client(mock_session: MagicMock) -> InstrumentsClient:
    return InstrumentsClient(mock_session)


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


def test_equity_option_instrument_parses() -> None:
    inst = EquityOptionInstrument.model_validate(make_equity_option_json())
    assert inst.symbol == "SPY   260320C00500000"
    assert inst.strike_price == Decimal("500.0")
    assert inst.option_type == OptionType.CALL
    assert inst.root_symbol == "SPY"
    assert inst.underlying_symbol == "SPY"
    assert inst.days_to_expiration == 20
    assert inst.shares_per_contract == 100
    assert inst.streamer_symbol == ".SPY260320C500"
    assert inst.active is True
    assert inst.is_closing_only is False


def test_equity_option_instrument_put() -> None:
    inst = EquityOptionInstrument.model_validate(
        make_equity_option_json(**{"option-type": "P", "strike-price": "305.0"})
    )
    assert inst.option_type == OptionType.PUT
    assert inst.strike_price == Decimal("305.0")


def test_future_option_instrument_parses() -> None:
    inst = FutureOptionInstrument.model_validate(make_future_option_json())
    assert inst.symbol == "./MESM6EX3H6 260320P6450"
    assert inst.underlying_symbol == "/MESM6"
    assert inst.product_code == "EX3"
    assert inst.strike_price == Decimal("6450.0")
    assert inst.option_type == OptionType.PUT
    assert inst.exchange == "CME"


def test_equity_instrument_parses() -> None:
    inst = EquityInstrument.model_validate(make_equity_json())
    assert inst.symbol == "SPY"
    assert inst.is_etf is True
    assert inst.active is True
    assert inst.description == "SPDR S&P 500 ETF Trust"


def test_future_instrument_parses() -> None:
    inst = FutureInstrument.model_validate(make_future_json())
    assert inst.symbol == "/MESM6"
    assert inst.product_code == "MES"
    assert inst.contract_size == Decimal("5.0")
    assert inst.notional_multiplier == Decimal("5.0")


def test_cryptocurrency_instrument_parses() -> None:
    inst = CryptocurrencyInstrument.model_validate(make_crypto_json())
    assert inst.symbol == "BTC/USD"
    assert inst.instrument_type == "Cryptocurrency"
    assert inst.active is True


def test_equity_option_instrument_is_frozen() -> None:
    from pydantic import ValidationError

    inst = EquityOptionInstrument.model_validate(make_equity_option_json())
    with pytest.raises(ValidationError):
        inst.symbol = "OTHER"  # type: ignore[misc]


def test_equity_option_instrument_allows_extra_fields() -> None:
    data = make_equity_option_json()
    data["expiration-type"] = "Weekly"
    data["option-chain-type"] = "Standard"
    inst = EquityOptionInstrument.model_validate(data)
    assert inst.symbol == data["symbol"]


def test_model_dump_json_uses_aliases() -> None:
    inst = EquityOptionInstrument.model_validate(make_equity_option_json())
    json_str = inst.model_dump_json(by_alias=True)
    assert "strike-price" in json_str
    assert "option-type" in json_str
    assert "underlying-symbol" in json_str


# ---------------------------------------------------------------------------
# InstrumentsClient tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_equity_options(
    client: InstrumentsClient, mock_session: MagicMock
) -> None:
    mock_session.session.get.return_value = make_ok_response(
        make_api_response([make_equity_option_json()])
    )

    result = await client.get_equity_options(["SPY   260320C00500000"])
    assert len(result) == 1
    assert isinstance(result[0], EquityOptionInstrument)
    assert result[0].strike_price == Decimal("500.0")


@pytest.mark.asyncio
async def test_get_future_options(
    client: InstrumentsClient, mock_session: MagicMock
) -> None:
    mock_session.session.get.return_value = make_ok_response(
        make_api_response([make_future_option_json()])
    )

    result = await client.get_future_options(["./MESM6EX3H6 260320P6450"])
    assert len(result) == 1
    assert isinstance(result[0], FutureOptionInstrument)


@pytest.mark.asyncio
async def test_get_equities(client: InstrumentsClient, mock_session: MagicMock) -> None:
    mock_session.session.get.return_value = make_ok_response(
        make_api_response([make_equity_json()])
    )

    result = await client.get_equities(["SPY"])
    assert len(result) == 1
    assert isinstance(result[0], EquityInstrument)


@pytest.mark.asyncio
async def test_get_futures(client: InstrumentsClient, mock_session: MagicMock) -> None:
    mock_session.session.get.return_value = make_ok_response(
        make_api_response([make_future_json()])
    )

    result = await client.get_futures(["/MESM6"])
    assert len(result) == 1
    assert isinstance(result[0], FutureInstrument)


@pytest.mark.asyncio
async def test_get_cryptocurrencies(
    client: InstrumentsClient, mock_session: MagicMock
) -> None:
    mock_session.session.get.return_value = make_ok_response(
        make_api_response([make_crypto_json()])
    )

    result = await client.get_cryptocurrencies(["BTC/USD"])
    assert len(result) == 1
    assert isinstance(result[0], CryptocurrencyInstrument)


@pytest.mark.asyncio
async def test_empty_symbols_returns_empty(
    client: InstrumentsClient, mock_session: MagicMock
) -> None:
    result = await client.get_equity_options([])
    assert result == []
    mock_session.session.get.assert_not_called()


@pytest.mark.asyncio
async def test_batch_size_respected(
    client: InstrumentsClient, mock_session: MagicMock
) -> None:
    """Many symbols should be batched into groups of INSTRUMENT_BATCH_SIZE."""
    symbols = [f"SYM{i}" for i in range(INSTRUMENT_BATCH_SIZE + 10)]
    mock_session.session.get.return_value = make_ok_response(make_api_response([]))

    await client.get_equity_options(symbols)
    assert mock_session.session.get.call_count == 2  # 50 + 10


@pytest.mark.asyncio
async def test_malformed_item_skipped(
    client: InstrumentsClient, mock_session: MagicMock
) -> None:
    """Malformed items in API response should be skipped, not crash."""
    mock_session.session.get.return_value = make_ok_response(
        make_api_response([make_equity_option_json(), {"bad": "data"}])
    )

    result = await client.get_equity_options(["SPY   260320C00500000"])
    assert len(result) == 1  # Only the valid one parsed


@pytest.mark.asyncio
async def test_url_construction(
    client: InstrumentsClient, mock_session: MagicMock
) -> None:
    mock_session.session.get.return_value = make_ok_response(make_api_response([]))

    await client.get_equity_options(["SPY   260320C00500000"])
    call_args = mock_session.session.get.call_args
    assert call_args[0][0] == "https://api.tastyworks.com/instruments/equity-options"
    # Check symbol[] params
    params = call_args[1]["params"]
    assert params == [("symbol[]", "SPY   260320C00500000")]
