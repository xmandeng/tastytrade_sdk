import logging
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, List, Literal, Optional, Union
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")


class Message(BaseModel):
    type: str
    channel: int
    headers: dict[str, Any]
    data: list[Any] | dict[str, Any]


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
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

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

    eventSymbol: str = Field(description="dxlink streamer symbol")
    timestamp: Annotated[
        datetime,
        Field(
            default_factory=lambda: datetime.now(MARKET_TZ),
            description="US Eastern Time timestamp when the event was validated",
        ),
    ]

    @model_validator(mode="after")
    def set_timestamp(self) -> "BaseEvent":
        """Set the timestamp after all other validations pass."""
        object.__setattr__(self, "timestamp", datetime.now(MARKET_TZ))
        return self


class TradeEvent(BaseEvent):
    price: Optional[Decimal] = Field(
        default=Decimal("0"),
        description="Execution price of the trade",
        ge=0,  # Greater than or equal to 0
    )
    dayVolume: Optional[Decimal] = Field(
        default=None,
        description="Cumulative volume for the trading day",
        ge=0,
    )
    size: Optional[Decimal] = Field(
        default=None,
        description="Size of the trade execution",
        ge=0,
    )

    @field_validator("price", "dayVolume", "size", mode="before")
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)


class QuoteEvent(BaseEvent):
    bidPrice: Decimal = Field(description="Best bid price", ge=0)
    askPrice: Decimal = Field(description="Best ask price", ge=0)
    bidSize: Optional[Decimal] = Field(description="Size available at bid price", ge=0)
    askSize: Optional[Decimal] = Field(description="Size available at ask price", ge=0)

    @field_validator("bidPrice", "askPrice", "bidSize", "askSize", mode="before")
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)


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
    shortSaleRestriction: str = Field(description="Short sale restriction status")
    tradingStatus: str = Field(description="Current trading status")
    statusReason: Optional[str] = Field(
        default=None, description="Reason for current trading status"
    )
    haltStartTime: Optional[int] = Field(default=None, description="Trading halt start timestamp")
    haltEndTime: Optional[int] = Field(default=None, description="Trading halt end timestamp")
    highLimitPrice: Optional[Decimal] = Field(default=None, description="Upper price limit", ge=0)
    lowLimitPrice: Optional[Decimal] = Field(default=None, description="Lower price limit", ge=0)
    high52WeekPrice: Optional[Decimal] = Field(default=None, description="52-week high price", ge=0)
    low52WeekPrice: Optional[Decimal] = Field(default=None, description="52-week low price", ge=0)

    @field_validator(
        "highLimitPrice",
        "lowLimitPrice",
        "high52WeekPrice",
        "low52WeekPrice",
        mode="before",
    )
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)

    @model_validator(mode="after")
    def validate_price_ranges(self) -> "ProfileEvent":
        """Validate price range relationships."""
        if (
            self.highLimitPrice is not None
            and self.lowLimitPrice is not None
            and self.highLimitPrice < self.lowLimitPrice
        ):
            raise ValueError("High limit price must be greater than low limit price")

        if (
            self.high52WeekPrice is not None
            and self.low52WeekPrice is not None
            and self.high52WeekPrice < self.low52WeekPrice
        ):
            raise ValueError("52-week high must be greater than 52-week low")

        return self


class SummaryEvent(BaseEvent):
    openInterest: Optional[Decimal] = Field(default=None, description="Open interest", ge=0)
    dayOpenPrice: Decimal = Field(description="Opening price for the day", ge=0)
    dayHighPrice: Decimal = Field(description="Highest price for the day", ge=0)
    dayLowPrice: Decimal = Field(description="Lowest price for the day", ge=0)
    prevDayClosePrice: Decimal = Field(description="Previous day's closing price", ge=0)

    @field_validator(
        "openInterest",
        "dayOpenPrice",
        "dayHighPrice",
        "dayLowPrice",
        "prevDayClosePrice",
        mode="before",
    )
    @classmethod
    def convert_decimal(cls, value: Any) -> Any:
        return to_decimal(value)

    @model_validator(mode="after")
    def validate_price_ranges(self) -> "SummaryEvent":
        """Validate daily price range relationships."""
        if self.dayHighPrice < self.dayLowPrice:
            raise ValueError("Day high price must be greater than day low price")

        if not (self.dayLowPrice <= self.dayHighPrice):
            raise ValueError("Day prices must maintain low <= high relationship")

        return self


EventType = TradeEvent | QuoteEvent | GreeksEvent | ProfileEvent | SummaryEvent | None
SingleEventType = Union[TradeEvent, QuoteEvent, GreeksEvent, ProfileEvent, SummaryEvent, None]
EventList = List[SingleEventType]
ParsedEventType = Union[SingleEventType, EventList]
