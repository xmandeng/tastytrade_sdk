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
    """Factory for equity option instrument API response.

    Mirrors the full 19-field shape returned by GET /instruments/equity-options.
    """
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
        "expiration-type": "Weekly",
        "market-time-instrument-collection": "Cash Settled Equity Option",
        "option-chain-type": "Standard",
        "stops-trading-at": "2026-03-20T20:15:00.000+00:00",
    }
    base.update(overrides)
    return base


def make_future_option_json(**overrides: Any) -> dict[str, Any]:
    """Factory for future option instrument API response.

    Mirrors the full 34-field shape returned by GET /instruments/future-options.
    """
    base: dict[str, Any] = {
        "symbol": "./MESM6EX3H6 260320P6450",
        "underlying-symbol": "/MESM6",
        "product-code": "EX3",
        "expiration-date": "2026-03-20",
        "strike-price": "6450.0",
        "option-type": "P",
        "exchange": "CME",
        "streamer-symbol": "./EX3H26P6450:XCME",
        "active": True,
        "days-to-expiration": 20,
        "display-factor": "0.01",
        "exchange-symbol": "EX3H6 P6450",
        "exercise-style": "American",
        "expires-at": "2026-03-20T17:30:00.000+00:00",
        "future-option-product": {
            "root-symbol": "EX3",
            "exchange": "CME",
            "product-type": "Physical",
        },
        "future-price-ratio": "1.0",
        "is-closing-only": False,
        "is-confirmed": True,
        "is-exercisable-weekly": True,
        "is-primary-deliverable": True,
        "is-vanilla": True,
        "last-trade-time": "0",
        "maturity-date": "2026-03-20",
        "multiplier": "1.0",
        "notional-value": "1.0",
        "option-root-symbol": "EX3",
        "root-symbol": "/MES",
        "security-exchange": "4",
        "security-id": "12345678",
        "settlement-type": "Future",
        "stops-trading-at": "2026-03-20T17:30:00.000+00:00",
        "strike-factor": "1.0",
        "sx-id": "0",
        "underlying-count": "1.0",
    }
    base.update(overrides)
    return base


def make_equity_json(**overrides: Any) -> dict[str, Any]:
    """Factory for equity instrument API response.

    Mirrors the full 27-field shape returned by GET /instruments/equities.
    """
    base: dict[str, Any] = {
        "symbol": "SPY",
        "instrument-type": "Equity",
        "description": "SPDR S&P 500 ETF TRUST",
        "is-etf": True,
        "active": True,
        "id": 27854,
        "cusip": "78462F103",
        "short-description": "SPDR S&P 500 ET",
        "streamer-symbol": "SPY",
        "is-closing-only": False,
        "is-index": False,
        "is-illiquid": False,
        "is-fraud-risk": False,
        "is-options-closing-only": False,
        "is-fractional-quantity-eligible": True,
        "bypass-manual-review": False,
        "overnight-trading-permitted": True,
        "borrow-rate": "0.0",
        "lendability": "Easy To Borrow",
        "instrument-sub-type": "ETF",
        "listed-market": "ARCX",
        "market-time-instrument-collection": "Equity",
        "country-of-incorporation": "US",
        "tick-sizes": [{"threshold": "1.0", "value": "0.0001"}, {"value": "0.01"}],
        "option-tick-sizes": [{"value": "0.01"}],
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
    # Fields discovered from live API
    assert inst.expiration_type == "Weekly"
    assert inst.market_time_instrument_collection == "Cash Settled Equity Option"
    assert inst.option_chain_type == "Standard"
    assert inst.stops_trading_at == "2026-03-20T20:15:00.000+00:00"


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
    # Fields discovered from live API
    assert inst.active is True
    assert inst.days_to_expiration == 20
    assert inst.exercise_style == "American"
    assert inst.settlement_type == "Future"
    assert inst.is_closing_only is False
    assert inst.root_symbol == "/MES"
    assert inst.option_root_symbol == "EX3"
    assert inst.is_vanilla is True


def test_equity_instrument_parses() -> None:
    inst = EquityInstrument.model_validate(make_equity_json())
    assert inst.symbol == "SPY"
    assert inst.is_etf is True
    assert inst.active is True
    assert inst.description == "SPDR S&P 500 ETF TRUST"
    # Fields discovered from live API
    assert inst.id == 27854
    assert inst.cusip == "78462F103"
    assert inst.streamer_symbol == "SPY"
    assert inst.is_closing_only is False
    assert inst.is_fractional_quantity_eligible is True
    assert inst.lendability == "Easy To Borrow"
    assert inst.instrument_sub_type == "ETF"
    assert inst.listed_market == "ARCX"
    assert inst.country_of_incorporation == "US"


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
    data["some-future-field"] = "unknown-value"
    data["another-new-field"] = 42
    inst = EquityOptionInstrument.model_validate(data)
    assert inst.symbol == data["symbol"]


def test_model_dump_json_uses_aliases() -> None:
    inst = EquityOptionInstrument.model_validate(make_equity_option_json())
    json_str = inst.model_dump_json(by_alias=True)
    assert "strike-price" in json_str
    assert "option-type" in json_str
    assert "underlying-symbol" in json_str


# ---------------------------------------------------------------------------
# API resilience tests — models must survive schema changes
# ---------------------------------------------------------------------------


def test_equity_option_fails_without_required_fields() -> None:
    """Option instruments must have strategy-critical fields — fail fast on bad data."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EquityOptionInstrument.model_validate({"symbol": "SPY   260320C00500000"})


def test_future_option_fails_without_required_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FutureOptionInstrument.model_validate({"symbol": "./MESM6EX3H6 260320P6450"})


def test_equity_option_survives_missing_informational_fields() -> None:
    """Informational fields are Optional — only strategy-critical ones are required."""
    data = {
        "symbol": "SPY   260320C00500000",
        "strike-price": "500.0",
        "option-type": "C",
        "underlying-symbol": "SPY",
        "expiration-date": "2026-03-20",
        "days-to-expiration": 20,
        "streamer-symbol": ".SPY260320C500",
    }
    inst = EquityOptionInstrument.model_validate(data)
    assert inst.symbol == "SPY   260320C00500000"
    assert inst.strike_price == Decimal("500.0")
    # Informational fields default to None
    assert inst.exercise_style is None
    assert inst.settlement_type is None
    assert inst.shares_per_contract is None


def test_equity_parses_with_only_symbol() -> None:
    """Equities only require symbol — no strategy-critical option fields."""
    inst = EquityInstrument.model_validate({"symbol": "SPY"})
    assert inst.symbol == "SPY"
    assert inst.is_etf is None
    assert inst.active is None


def test_future_parses_with_only_symbol() -> None:
    inst = FutureInstrument.model_validate({"symbol": "/MESM6"})
    assert inst.symbol == "/MESM6"
    assert inst.product_code is None


def test_crypto_parses_with_only_symbol() -> None:
    inst = CryptocurrencyInstrument.model_validate({"symbol": "BTC/USD"})
    assert inst.symbol == "BTC/USD"
    assert inst.instrument_type is None


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
