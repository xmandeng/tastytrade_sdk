import logging
from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tastytrade.utils.helpers import format_candle_symbol

logger = logging.getLogger(__name__)


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

    def __init__(self, **data: Any) -> None:
        msg_type = data.get("type")
        msg_channel = data.get("channel", 0)

        super().__init__(type=msg_type, channel=msg_channel, fields=data)

    def __getattr__(self, name: str) -> Any:
        """Allow access to fields as attributes"""
        if name in self.fields:
            return self.fields[name]
        logger.error(f"'{type(self).__name__}' object has no attribute '{name}'")
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

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


class CancelItem(AddItem):
    type: str
    symbol: str


class AddCandleItem(BaseModel):
    type: str
    symbol: str
    fromTime: Optional[int] = None
    toTime: Optional[int] = None


class CancelCandleItem(BaseModel):
    type: str
    symbol: str


class SubscriptionRequest(BaseModel):
    type: str = "FEED_SUBSCRIPTION"
    channel: int
    reset: bool = False
    add: Optional[List[AddItem | AddCandleItem]] = Field(default_factory=lambda: list())
    remove: Optional[List[CancelItem | CancelCandleItem]] = Field(
        default_factory=lambda: list()
    )


class CandleSubscriptionRequest(BaseModel):
    symbol: str
    interval: str
    from_time: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000)
    )
    to_time: Optional[int] = None

    @staticmethod
    def parse_interval(interval: str) -> int:
        """Parse interval string into milliseconds.

        Args:
            interval: String like "1m", "6s", "3h", etc.

        Returns
            Interval in milliseconds

        Examples
            CandleSubscriptionRequest.parse_interval("1m")
            60000
            CandleSubscriptionRequest.parse_interval("6s")
            6000
            CandleSubscriptionRequest.parse_interval("3h")
            10800000
        """
        if not interval:
            raise ValueError("Interval cannot be empty")

        # Extract number and unit
        import re

        match = re.match(r"(\d*)([smhdw])", interval.lower())
        if not match:
            raise ValueError(f"Invalid interval format: {interval}")

        number = int(match.group(1))
        unit = match.group(2)

        # Convert to milliseconds

        second = 1000
        minute = 60 * second
        hour = 60 * minute
        day = 24 * hour
        week = 7 * day

        multipliers = {
            "s": second,
            "m": minute,
            "h": hour,
            "d": day,
            "w": week,
        }

        return number * multipliers[unit]

    @field_validator("from_time", "to_time", mode="before")
    @classmethod
    def convert_datetime_to_epoch(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return int(value.timestamp() * 1000)
        return value

    @model_validator(mode="after")
    def round_from_time(self) -> "CandleSubscriptionRequest":
        """Round from_time down to the nearest interval boundary."""
        try:
            interval_ms = self.parse_interval(
                "1m" if self.interval == "m" else self.interval
            )
            self.from_time = (self.from_time // interval_ms) * interval_ms
        except ValueError as e:
            logger.warning(f"Could not parse interval '{self.interval}': {e}")
            # We could either raise the error or just pass through the timestamp unmodified
            # For now, we'll just log and continue
            pass

        return self

    @field_validator("interval", mode="before")
    @classmethod
    def validate_interval(cls, interval: str) -> str:
        return "m" if interval == "1m" else interval

    @property
    def formatted(self) -> str:
        return format_candle_symbol(f"{self.symbol}{{={self.interval}}}")


class CancelCandleSubscriptionRequest(BaseModel):
    symbol: str
    interval: str  # e.g., "1m", "5m", "1h", "1d"

    @field_validator("interval", mode="before")
    @classmethod
    def validate_interval(cls, interval: str) -> str:
        return "m" if interval == "1m" else interval
