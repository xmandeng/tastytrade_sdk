"""Instrument models for TastyTrade API instrument endpoints.

Each model maps 1:1 to its TT API ``/instruments/*`` endpoint.
All extend TastyTradeApiModel (frozen Pydantic).
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class OptionType(str, Enum):
    CALL = "C"
    PUT = "P"


class InstrumentModel(BaseModel):
    """Base model for instrument API responses.

    Separate from TastyTradeApiModel to avoid circular imports
    (market.models <-> accounts.publisher). Uses extra="ignore"
    since the TT API returns many fields we don't need.
    """

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class EquityOptionInstrument(InstrumentModel):
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


class FutureOptionInstrument(InstrumentModel):
    symbol: str = Field(alias="symbol")
    underlying_symbol: str = Field(alias="underlying-symbol")
    product_code: str = Field(alias="product-code")
    expiration_date: date = Field(alias="expiration-date")
    strike_price: Decimal = Field(alias="strike-price")
    option_type: OptionType = Field(alias="option-type")
    exchange: str = Field(alias="exchange")
    streamer_symbol: str = Field(alias="streamer-symbol")


class EquityInstrument(InstrumentModel):
    symbol: str = Field(alias="symbol")
    instrument_type: str = Field(alias="instrument-type")
    description: Optional[str] = Field(default=None, alias="description")
    is_etf: bool = Field(alias="is-etf")
    active: bool = Field(alias="active")


class FutureInstrument(InstrumentModel):
    symbol: str = Field(alias="symbol")
    product_code: str = Field(alias="product-code")
    contract_size: Decimal = Field(alias="contract-size")
    notional_multiplier: Decimal = Field(alias="notional-multiplier")
    expiration_date: date = Field(alias="expiration-date")
    active: bool = Field(alias="active")


class CryptocurrencyInstrument(InstrumentModel):
    symbol: str = Field(alias="symbol")
    instrument_type: str = Field(alias="instrument-type")
    description: Optional[str] = Field(default=None, alias="description")
    active: bool = Field(alias="active")
