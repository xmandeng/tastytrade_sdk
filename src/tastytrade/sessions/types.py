# central location for your data structures, models, and schemas

import logging
from decimal import Decimal
from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


class Message(BaseModel):
    type: str
    channel: int
    headers: dict[str, Any]
    data: list[Any]


class SetupModel(BaseModel):
    type: Literal["SETUP"] = "SETUP"
    channel: int = 0
    version: str = "0.1-DXF-JS/0.3.0"
    keepaliveTimeout: int = 60
    acceptKeepaliveTimeout: int = 60

    class Config:
        frozen = True
        extra = "forbid"


class AuthModel(BaseModel):
    type: Literal["AUTH"] = "AUTH"
    channel: int = 0
    token: str

    class Config:
        frozen = True
        extra = "forbid"


class OpenChannelModel(BaseModel):
    type: Literal["CHANNEL_REQUEST"] = "CHANNEL_REQUEST"
    service: str = "FEED"
    channel: int
    parameters: dict[str, Any] = {"contract": "AUTO"}

    class Config:
        frozen = True
        extra = "forbid"


class KeepaliveModel(BaseModel):
    type: Literal["KEEPALIVE"] = "KEEPALIVE"
    channel: int = 0

    class Config:
        frozen = True
        extra = "forbid"


class SessionReceivedModel(BaseModel):
    """Model that requires type and channel, but can handle any other fields dynamically"""

    type: str
    channel: int = 0
    fields: dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        msg_type = data.get("type")
        msg_channel = data.get("channel", 0)

        super().__init__(type=msg_type, channel=msg_channel, fields=data)

    def __getattr__(self, name: str) -> Any:
        """Allow access to fields as attributes"""
        if name in self.fields:
            return self.fields[name]
        logger.error(f"'{type(self).__name__}' object has no attribute '{name}'")
        # raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def get(self, key: str, default: Any = None) -> Any:
        """Safely get any field"""
        if key == "type":
            return self.type
        if key == "channel":
            return self.channel
        return self.fields.get(key, default)

    @property
    def raw(self) -> dict[str, Any]:
        """Access the raw dictionary data"""
        return {"type": self.type, "channel": self.channel, **self.fields}


class FeedSetupModel(BaseModel):
    type: str = "FEED_SETUP"
    acceptAggregationPeriod: float = 0.1
    acceptDataFormat: str = "COMPACT"
    acceptEventFields: dict[str, List[str]]
    channel: int


class AddItem(BaseModel):
    type: str
    symbol: str


class SubscriptionRequest(BaseModel):
    type: str = "FEED_SUBSCRIPTION"
    channel: int
    reset: bool = True
    add: List[AddItem]


def to_decimal(value: str | float | None) -> Optional[Decimal]:
    """Convert value to Decimal, handling NaN and None cases."""
    if value is None or value == "NaN" or value == float("inf"):
        return None
    return Decimal(str(value))


def dash_to_underscore(value: str) -> str:
    return value.replace("-", "_")


class BaseEvent(BaseModel):
    model_config = ConfigDict(
        frozen=True,  # Make models immutable
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    symbol: str = Field(description="dxlink streamer symbol")


class TradeEvent(BaseEvent):
    price: Optional[Decimal] = Field(
        default=Decimal("0"),
        description="Execution price of the trade",
        ge=0,  # Greater than or equal to 0
    )
    day_volume: Optional[Decimal] = Field(
        default=None,
        description="Cumulative volume for the trading day",
        ge=0,
    )
    size: Optional[Decimal] = Field(
        default=None,
        description="Size of the trade execution",
        ge=0,
    )

    @field_validator("price", "day_volume", "size", mode="before")
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)


class QuoteEvent(BaseEvent):
    bid_price: Decimal = Field(description="Best bid price", ge=0)
    ask_price: Decimal = Field(description="Best ask price", ge=0)
    bid_size: Optional[Decimal] = Field(description="Size available at bid price", ge=0)
    ask_size: Optional[Decimal] = Field(description="Size available at ask price", ge=0)

    @field_validator("bid_price", "ask_price", "bid_size", "ask_size", mode="before")
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)

    @model_validator(mode="after")
    def validate_spread(self) -> "QuoteEvent":
        """Validate that ask price is greater than bid price."""
        if self.ask_price < self.bid_price:
            raise ValueError("Ask price must be greater than bid price")
        return self


class GreeksEvent(BaseEvent):
    volatility: Optional[Decimal] = Field(description="Implied volatility", ge=0)
    delta: Optional[Decimal] = Field(description="Delta greek", ge=-1, le=1)
    gamma: Optional[Decimal] = Field(description="Gamma greek", ge=0)
    theta: Optional[Decimal] = Field(description="Theta greek")
    rho: Optional[Decimal] = Field(description="Rho greek")
    vega: Optional[Decimal] = Field(description="Vega greek", ge=0)

    @field_validator("volatility", "delta", "gamma", "theta", "rho", "vega", mode="before")
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)


class ProfileEvent(BaseEvent):
    description: str = Field(description="Instrument description")
    short_sale_restriction: str = Field(description="Short sale restriction status")
    trading_status: str = Field(description="Current trading status")
    status_reason: Optional[str] = Field(
        default=None, description="Reason for current trading status"
    )
    halt_start_time: Optional[int] = Field(default=None, description="Trading halt start timestamp")
    halt_end_time: Optional[int] = Field(default=None, description="Trading halt end timestamp")
    high_limit_price: Optional[Decimal] = Field(default=None, description="Upper price limit", ge=0)
    low_limit_price: Optional[Decimal] = Field(default=None, description="Lower price limit", ge=0)
    high_52_week_price: Optional[Decimal] = Field(
        default=None, description="52-week high price", ge=0
    )
    low_52_week_price: Optional[Decimal] = Field(
        default=None, description="52-week low price", ge=0
    )

    @field_validator(
        "high_limit_price",
        "low_limit_price",
        "high_52_week_price",
        "low_52_week_price",
        mode="before",
    )
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)

    @model_validator(mode="after")
    def validate_price_ranges(self) -> "ProfileEvent":
        """Validate price range relationships."""
        if (
            self.high_limit_price is not None
            and self.low_limit_price is not None
            and self.high_limit_price < self.low_limit_price
        ):
            raise ValueError("High limit price must be greater than low limit price")

        if (
            self.high_52_week_price is not None
            and self.low_52_week_price is not None
            and self.high_52_week_price < self.low_52_week_price
        ):
            raise ValueError("52-week high must be greater than 52-week low")

        return self


class SummaryEvent(BaseEvent):
    open_interest: Optional[Decimal] = Field(default=None, description="Open interest", ge=0)
    day_open_price: Decimal = Field(description="Opening price for the day", ge=0)
    day_high_price: Decimal = Field(description="Highest price for the day", ge=0)
    day_low_price: Decimal = Field(description="Lowest price for the day", ge=0)
    prev_day_close_price: Decimal = Field(description="Previous day's closing price", ge=0)

    @field_validator(
        "open_interest",
        "day_open_price",
        "day_high_price",
        "day_low_price",
        "prev_day_close_price",
        mode="before",
    )
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)

    @model_validator(mode="after")
    def validate_price_ranges(self) -> "SummaryEvent":
        """Validate daily price range relationships."""
        if self.day_high_price < self.day_low_price:
            raise ValueError("Day high price must be greater than day low price")

        if not (self.day_low_price <= self.day_high_price):
            raise ValueError("Day prices must maintain low <= high relationship")

        return self


EventType = TradeEvent | QuoteEvent | GreeksEvent | ProfileEvent | SummaryEvent | None
SingleEventType = Union[TradeEvent, QuoteEvent, GreeksEvent, ProfileEvent, SummaryEvent, None]
EventList = List[SingleEventType]
ParsedEventType = Union[SingleEventType, EventList]
