import logging
from datetime import datetime
from typing import Annotated, Any, List, Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")

MAX_PRECISION = 2


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
    model_config = ConfigDict(frozen=True, extra="forbid")


class AuthModel(BaseModel):
    type: Literal["AUTH"] = "AUTH"
    channel: int = 0
    token: str
    model_config = ConfigDict(frozen=True, extra="forbid")


class OpenChannelModel(BaseModel):
    type: Literal["CHANNEL_REQUEST"] = "CHANNEL_REQUEST"
    service: str = "FEED"
    channel: int
    parameters: dict[str, Any] = {"contract": "AUTO"}
    model_config = ConfigDict(frozen=True, extra="forbid")


class KeepaliveModel(BaseModel):
    type: Literal["KEEPALIVE"] = "KEEPALIVE"
    channel: int = 0
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventReceivedModel(BaseModel):
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


class FloatFieldMixin:

    @classmethod
    def validate_float_fields(cls, *field_names):
        @field_validator(*field_names, mode="before")
        @classmethod
        def convert_float(cls, value: Any) -> Any:
            if value is None or value == "NaN" or value == float("inf"):
                return None
            return round(float(value), MAX_PRECISION)

        return convert_float


class TradeEvent(BaseEvent, FloatFieldMixin):
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


class ControlEvent(BaseModel):
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=False,
        extra="allow",
        str_strip_whitespace=True,
    )
