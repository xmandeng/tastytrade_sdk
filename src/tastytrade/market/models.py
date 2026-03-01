"""Instrument models for TastyTrade API instrument endpoints.

Each model maps 1:1 to its TT API ``/instruments/*`` endpoint.
All extend InstrumentModel (frozen Pydantic with extra="allow").

Field inventory sourced from live TT API responses (2026-02-28).
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class OptionType(str, Enum):
    CALL = "C"
    PUT = "P"


class InstrumentModel(BaseModel):
    """Base model for instrument API responses.

    Separate from TastyTradeApiModel to avoid circular imports
    (market.models <-> accounts.publisher). Uses extra="allow"
    to preserve any new fields the TT API adds in the future.
    """

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class EquityOptionInstrument(InstrumentModel):
    """Equity option instrument from GET /instruments/equity-options.

    All 19 fields observed in live API responses (2026-02-28).
    """

    symbol: str = Field(alias="symbol")
    instrument_type: str = Field(alias="instrument-type")
    strike_price: Decimal = Field(alias="strike-price")
    option_type: OptionType = Field(alias="option-type")
    root_symbol: str = Field(alias="root-symbol")
    underlying_symbol: str = Field(alias="underlying-symbol")
    expiration_date: date = Field(alias="expiration-date")
    days_to_expiration: int = Field(alias="days-to-expiration")
    expires_at: datetime = Field(alias="expires-at")
    exercise_style: str = Field(alias="exercise-style")
    settlement_type: str = Field(alias="settlement-type")
    shares_per_contract: int = Field(alias="shares-per-contract")
    streamer_symbol: str = Field(alias="streamer-symbol")
    active: bool = Field(alias="active")
    is_closing_only: bool = Field(alias="is-closing-only")
    # Fields discovered in live API (not in original plan)
    expiration_type: Optional[str] = Field(default=None, alias="expiration-type")
    market_time_instrument_collection: Optional[str] = Field(
        default=None, alias="market-time-instrument-collection"
    )
    option_chain_type: Optional[str] = Field(default=None, alias="option-chain-type")
    stops_trading_at: Optional[str] = Field(default=None, alias="stops-trading-at")


class FutureOptionInstrument(InstrumentModel):
    """Future option instrument from GET /instruments/future-options.

    All 34 fields observed in live API responses (2026-02-28).
    """

    symbol: str = Field(alias="symbol")
    underlying_symbol: str = Field(alias="underlying-symbol")
    product_code: str = Field(alias="product-code")
    expiration_date: date = Field(alias="expiration-date")
    strike_price: Decimal = Field(alias="strike-price")
    option_type: OptionType = Field(alias="option-type")
    exchange: str = Field(alias="exchange")
    streamer_symbol: str = Field(alias="streamer-symbol")
    # Fields discovered in live API (not in original plan)
    active: bool = Field(default=True, alias="active")
    days_to_expiration: int = Field(default=0, alias="days-to-expiration")
    display_factor: Optional[str] = Field(default=None, alias="display-factor")
    exchange_symbol: Optional[str] = Field(default=None, alias="exchange-symbol")
    exercise_style: Optional[str] = Field(default=None, alias="exercise-style")
    expires_at: Optional[str] = Field(default=None, alias="expires-at")
    future_option_product: Optional[dict[str, Any]] = Field(
        default=None, alias="future-option-product"
    )
    future_price_ratio: Optional[str] = Field(default=None, alias="future-price-ratio")
    is_closing_only: bool = Field(default=False, alias="is-closing-only")
    is_confirmed: Optional[bool] = Field(default=None, alias="is-confirmed")
    is_exercisable_weekly: Optional[bool] = Field(
        default=None, alias="is-exercisable-weekly"
    )
    is_primary_deliverable: Optional[bool] = Field(
        default=None, alias="is-primary-deliverable"
    )
    is_vanilla: Optional[bool] = Field(default=None, alias="is-vanilla")
    last_trade_time: Optional[str] = Field(default=None, alias="last-trade-time")
    maturity_date: Optional[date] = Field(default=None, alias="maturity-date")
    multiplier: Optional[str] = Field(default=None, alias="multiplier")
    notional_value: Optional[str] = Field(default=None, alias="notional-value")
    option_root_symbol: Optional[str] = Field(default=None, alias="option-root-symbol")
    root_symbol: Optional[str] = Field(default=None, alias="root-symbol")
    security_exchange: Optional[str] = Field(default=None, alias="security-exchange")
    security_id: Optional[str] = Field(default=None, alias="security-id")
    settlement_type: Optional[str] = Field(default=None, alias="settlement-type")
    stops_trading_at: Optional[str] = Field(default=None, alias="stops-trading-at")
    strike_factor: Optional[str] = Field(default=None, alias="strike-factor")
    sx_id: Optional[str] = Field(default=None, alias="sx-id")
    underlying_count: Optional[str] = Field(default=None, alias="underlying-count")


class EquityInstrument(InstrumentModel):
    """Equity instrument from GET /instruments/equities.

    All 27 fields observed in live API responses (2026-02-28).
    """

    symbol: str = Field(alias="symbol")
    instrument_type: str = Field(alias="instrument-type")
    description: Optional[str] = Field(default=None, alias="description")
    is_etf: bool = Field(alias="is-etf")
    active: bool = Field(alias="active")
    # Fields discovered in live API (not in original plan)
    id: Optional[int] = Field(default=None, alias="id")
    cusip: Optional[str] = Field(default=None, alias="cusip")
    short_description: Optional[str] = Field(default=None, alias="short-description")
    streamer_symbol: Optional[str] = Field(default=None, alias="streamer-symbol")
    is_closing_only: bool = Field(default=False, alias="is-closing-only")
    is_index: bool = Field(default=False, alias="is-index")
    is_illiquid: bool = Field(default=False, alias="is-illiquid")
    is_fraud_risk: bool = Field(default=False, alias="is-fraud-risk")
    is_options_closing_only: bool = Field(
        default=False, alias="is-options-closing-only"
    )
    is_fractional_quantity_eligible: bool = Field(
        default=False, alias="is-fractional-quantity-eligible"
    )
    bypass_manual_review: bool = Field(default=False, alias="bypass-manual-review")
    overnight_trading_permitted: bool = Field(
        default=False, alias="overnight-trading-permitted"
    )
    borrow_rate: Optional[str] = Field(default=None, alias="borrow-rate")
    lendability: Optional[str] = Field(default=None, alias="lendability")
    instrument_sub_type: Optional[str] = Field(
        default=None, alias="instrument-sub-type"
    )
    listed_market: Optional[str] = Field(default=None, alias="listed-market")
    market_time_instrument_collection: Optional[str] = Field(
        default=None, alias="market-time-instrument-collection"
    )
    country_of_incorporation: Optional[str] = Field(
        default=None, alias="country-of-incorporation"
    )
    country_of_taxation: Optional[str] = Field(
        default=None, alias="country-of-taxation"
    )
    tick_sizes: Optional[list[dict[str, str]]] = Field(default=None, alias="tick-sizes")
    option_tick_sizes: Optional[list[dict[str, str]]] = Field(
        default=None, alias="option-tick-sizes"
    )


class FutureInstrument(InstrumentModel):
    """Future instrument from GET /instruments/futures.

    Core fields defined; no live data available for full inventory.
    extra="allow" will capture any additional fields.
    """

    symbol: str = Field(alias="symbol")
    product_code: str = Field(alias="product-code")
    contract_size: Decimal = Field(alias="contract-size")
    notional_multiplier: Decimal = Field(alias="notional-multiplier")
    expiration_date: date = Field(alias="expiration-date")
    active: bool = Field(alias="active")


class CryptocurrencyInstrument(InstrumentModel):
    """Cryptocurrency instrument from GET /instruments/cryptocurrencies.

    Core fields defined; no live data available for full inventory.
    extra="allow" will capture any additional fields.
    """

    symbol: str = Field(alias="symbol")
    instrument_type: str = Field(alias="instrument-type")
    description: Optional[str] = Field(default=None, alias="description")
    active: bool = Field(alias="active")
