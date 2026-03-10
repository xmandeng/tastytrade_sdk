import logging
from datetime import datetime
from typing import Any, Callable, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# Maximum decimal places preserved on DXLink float fields (prices, sizes, Greeks).
# Must be high enough to retain micro-premium prices from FX futures options
# (e.g. /6E puts at 0.00390) while still trimming IEEE 754 representation noise
# (e.g. 600.2499999999999998). 10 digits covers all exchange tick sizes.
FLOAT_PRECISION: int = 10


class ControlEvent(BaseModel):
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=False,
        extra="allow",
        str_strip_whitespace=True,
    )


class BaseEvent(BaseModel):
    model_config = ConfigDict(
        frozen=True,  # Make models immutable
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
    )

    eventSymbol: str = Field(description="dxlink streamer symbol")


class FloatFieldMixin:
    @classmethod
    def validate_float_fields(
        cls, *field_names: str
    ) -> Callable[[Any], Optional[float]]:
        @field_validator(*field_names, mode="before")
        def convert_float(value: Any) -> Optional[float]:
            if (
                value is None
                or value == "NaN"
                or value == float("inf")
                or pd.isna(value)
            ):
                return None
            return round(float(value), FLOAT_PRECISION)

        return convert_float


class TradeEvent(BaseEvent, FloatFieldMixin):
    time: Optional[datetime] = Field(default=None, description="Event timestamp")
    price: Optional[float] = Field(
        default=None,
        description="Execution price of the trade",
    )
    dayVolume: Optional[float] = Field(
        default=None,
        description="Cumulative volume for the trading day",
    )
    size: Optional[float] = Field(
        default=None,
        description="Size of the trade execution",
    )

    convert_float = FloatFieldMixin.validate_float_fields("price", "dayVolume", "size")


class QuoteEvent(BaseEvent, FloatFieldMixin):
    bidPrice: float = Field(description="Best bid price")
    askPrice: float = Field(description="Best ask price")
    bidSize: Optional[float] = Field(description="Size available at bid price")
    askSize: Optional[float] = Field(description="Size available at ask price")

    convert_float = FloatFieldMixin.validate_float_fields(
        "bidPrice", "askPrice", "bidSize", "askSize"
    )


class GreeksEvent(BaseEvent, FloatFieldMixin):
    time: Optional[datetime] = Field(default=None, description="Event timestamp")
    volatility: Optional[float] = Field(description="Implied volatility")
    delta: Optional[float] = Field(description="Delta greek")
    gamma: Optional[float] = Field(description="Gamma greek")
    theta: Optional[float] = Field(description="Theta greek")
    rho: Optional[float] = Field(description="Rho greek")
    vega: Optional[float] = Field(description="Vega greek")

    convert_float = FloatFieldMixin.validate_float_fields(
        "volatility", "delta", "gamma", "theta", "rho", "vega"
    )


class ProfileEvent(BaseEvent, FloatFieldMixin):
    description: str = Field(description="Instrument description")
    shortSaleRestriction: str = Field(description="Short sale restriction status")
    tradingStatus: str = Field(description="Current trading status")
    statusReason: Optional[str] = Field(
        default=None, description="Reason for current trading status"
    )
    haltStartTime: Optional[int] = Field(
        default=None, description="Trading halt start timestamp"
    )
    haltEndTime: Optional[int] = Field(
        default=None, description="Trading halt end timestamp"
    )
    highLimitPrice: Optional[float] = Field(
        default=None, description="Upper price limit"
    )
    lowLimitPrice: Optional[float] = Field(
        default=None, description="Lower price limit"
    )
    high52WeekPrice: Optional[float] = Field(
        default=None, description="52-week high price"
    )
    low52WeekPrice: Optional[float] = Field(
        default=None, description="52-week low price"
    )

    convert_float = FloatFieldMixin.validate_float_fields(
        "highLimitPrice", "lowLimitPrice", "high52WeekPrice", "low52WeekPrice"
    )


class SummaryEvent(BaseEvent, FloatFieldMixin):
    openInterest: Optional[float] = Field(default=None, description="Open interest")
    dayOpenPrice: Optional[float] = Field(description="Opening price for the day")
    dayHighPrice: Optional[float] = Field(description="Highest price for the day")
    dayLowPrice: Optional[float] = Field(description="Lowest price for the day")
    prevDayClosePrice: Optional[float] = Field(
        description="Previous day's closing price"
    )

    convert_float = FloatFieldMixin.validate_float_fields(
        "openInterest",
        "dayOpenPrice",
        "dayHighPrice",
        "dayLowPrice",
        "prevDayClosePrice",
    )


class CandleEvent(BaseEvent, FloatFieldMixin):
    time: datetime = Field(description="Event timestamp")
    eventFlags: Optional[int] = Field(default=None, description="Event flags")
    index: Optional[int] = Field(
        default=None, description="Unique per-symbol index of this candle event"
    )
    sequence: Optional[int] = Field(
        default=None, description="Sequence number of this event"
    )
    count: Optional[int] = Field(
        default=None, description="Total number of events in the candle"
    )
    open: Optional[float] = Field(
        default=None, description="Opening price for the interval"
    )
    high: Optional[float] = Field(
        default=None, description="Highest price during the interval"
    )
    low: Optional[float] = Field(
        default=None, description="Lowest price during the interval"
    )
    close: Optional[float] = Field(
        default=None, description="Closing price for the interval"
    )
    volume: Optional[float] = Field(
        default=None, description="Volume of trades during the interval"
    )
    bidVolume: Optional[float] = Field(
        default=None, description="Bid volume of trades during the interval"
    )
    askVolume: Optional[float] = Field(
        default=None, description="Ask volume of trades during the interval"
    )
    openInterest: Optional[float] = Field(default=None, description="Open interest")
    vwap: Optional[float] = Field(
        default=None, description="Volume Weighted Average Price"
    )
    impVolatility: Optional[float] = Field(
        default=None, description="Implied volatility"
    )

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
    )

    convert_float = FloatFieldMixin.validate_float_fields(
        "open",
        "high",
        "low",
        "close",
        "volume",
        "bidVolume",
        "askVolume",
        "openInterest",
        "vwap",
        "impVolatility",
    )


class StudyEvent(BaseEvent):
    time: Optional[datetime] = Field(default=None, description="Event timestamp")
    name: str = Field(description="Study name")
    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
    )
