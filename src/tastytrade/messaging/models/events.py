import logging
from datetime import datetime
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

MAX_PRECISION = 2


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
        extra="forbid",
        str_strip_whitespace=True,
    )

    eventSymbol: str = Field(description="dxlink streamer symbol")


class FloatFieldMixin:
    @classmethod
    def validate_float_fields(cls, *field_names: str) -> Callable[[Any], Optional[float]]:
        @field_validator(*field_names, mode="before")
        def convert_float(value: Any) -> Optional[float]:
            if value is None or value == "NaN" or value == float("inf"):
                return None
            return round(float(value), MAX_PRECISION)

        return convert_float


class TradeEvent(BaseEvent, FloatFieldMixin):
    time: Optional[datetime] = Field(default=None, description="Event timestamp")
    price: Optional[float] = Field(
        default=None,
        description="Execution price of the trade",
        ge=0,
    )
    dayVolume: Optional[float] = Field(
        default=None,
        description="Cumulative volume for the trading day",
        ge=0,
    )
    size: Optional[float] = Field(
        default=None,
        description="Size of the trade execution",
        ge=0,
    )

    convert_float = FloatFieldMixin.validate_float_fields("price", "dayVolume", "size")


class QuoteEvent(BaseEvent, FloatFieldMixin):
    bidPrice: float = Field(description="Best bid price", ge=0)
    askPrice: float = Field(description="Best ask price", ge=0)
    bidSize: Optional[float] = Field(description="Size available at bid price", ge=0)
    askSize: Optional[float] = Field(description="Size available at ask price", ge=0)

    convert_float = FloatFieldMixin.validate_float_fields(
        "bidPrice", "askPrice", "bidSize", "askSize"
    )


class GreeksEvent(BaseEvent, FloatFieldMixin):
    time: Optional[datetime] = Field(default=None, description="Event timestamp")
    volatility: Optional[float] = Field(description="Implied volatility", ge=0)
    delta: Optional[float] = Field(description="Delta greek", ge=-1, le=1)
    gamma: Optional[float] = Field(description="Gamma greek", ge=0)
    theta: Optional[float] = Field(description="Theta greek")
    rho: Optional[float] = Field(description="Rho greek")
    vega: Optional[float] = Field(description="Vega greek", ge=0)

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
    haltStartTime: Optional[int] = Field(default=None, description="Trading halt start timestamp")
    haltEndTime: Optional[int] = Field(default=None, description="Trading halt end timestamp")
    highLimitPrice: Optional[float] = Field(default=None, description="Upper price limit", ge=0)
    lowLimitPrice: Optional[float] = Field(default=None, description="Lower price limit", ge=0)
    high52WeekPrice: Optional[float] = Field(default=None, description="52-week high price", ge=0)
    low52WeekPrice: Optional[float] = Field(default=None, description="52-week low price", ge=0)

    convert_float = FloatFieldMixin.validate_float_fields(
        "highLimitPrice", "lowLimitPrice", "high52WeekPrice", "low52WeekPrice"
    )


class SummaryEvent(BaseEvent, FloatFieldMixin):
    openInterest: Optional[float] = Field(default=None, description="Open interest", ge=0)
    dayOpenPrice: Optional[float] = Field(description="Opening price for the day", ge=0)
    dayHighPrice: Optional[float] = Field(description="Highest price for the day", ge=0)
    dayLowPrice: Optional[float] = Field(description="Lowest price for the day", ge=0)
    prevDayClosePrice: Optional[float] = Field(description="Previous day's closing price", ge=0)

    convert_float = FloatFieldMixin.validate_float_fields(
        "openInterest", "dayOpenPrice", "dayHighPrice", "dayLowPrice", "prevDayClosePrice"
    )


class RawCandleEvent(BaseEvent, FloatFieldMixin):
    time: datetime = Field(description="Event timestamp")
    eventFlags: Optional[int] = Field(default=None, description="Event flags")
    index: Optional[int] = Field(
        default=None, description="Unique per-symbol index of this candle event"
    )
    sequence: Optional[int] = Field(default=None, description="Sequence number of this event")
    count: Optional[int] = Field(default=None, description="Total number of events in the candle")
    open: Optional[float] = Field(default=None, description="Opening price for the interval", ge=0)
    high: Optional[float] = Field(
        default=None, description="Highest price during the interval", ge=0
    )
    low: Optional[float] = Field(default=None, description="Lowest price during the interval", ge=0)
    close: Optional[float] = Field(default=None, description="Closing price for the interval", ge=0)
    volume: Optional[float] = Field(
        default=None, description="Volume of trades during the interval", ge=0
    )
    bidVolume: Optional[float] = Field(
        default=None, description="Bid volume of trades during the interval", ge=0
    )
    askVolume: Optional[float] = Field(
        default=None, description="Ask volume of trades during the interval", ge=0
    )
    openInterest: Optional[float] = Field(default=None, description="Open interest", ge=0)
    vwap: Optional[float] = Field(default=None, description="Volume Weighted Average Price", ge=0)
    impVolatility: Optional[float] = Field(default=None, description="Implied volatility", ge=0)

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


class CandleEvent(RawCandleEvent):
    tradeDate: Optional[str] = Field(default=None, description="Trade date for the candle")
    tradeTime: Optional[str] = Field(default=None, description="Trade time for the candle")

    prevOpen: Optional[float] = Field(
        default=None, description="Opening price for the interval", ge=0
    )
    prevHigh: Optional[float] = Field(
        default=None, description="Highest price during the interval", ge=0
    )
    prevLow: Optional[float] = Field(
        default=None, description="Lowest price during the interval", ge=0
    )
    prevClose: Optional[float] = Field(
        default=None, description="Closing price for the interval", ge=0
    )
    prevDate: Optional[str] = Field(default=None, description="Trade date for the prev candle")
    prevTime: Optional[str] = Field(default=None, description="Trade time for the prev candle")


class StudyEvent(BaseEvent):
    time: Optional[datetime] = Field(default=None, description="Event timestamp")
    name: str = Field(description="Study name")
    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
    )
