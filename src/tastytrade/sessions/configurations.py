# central local for session configurations

from dataclasses import dataclass
from enum import Enum
from typing import List, Type

from tastytrade.sessions.types import (
    GreeksEvent,
    ProfileEvent,
    QuoteEvent,
    SummaryEvent,
    TradeEvent,
)


class Channels(Enum):
    Control = 0
    Trades = 1
    Quotes = 3
    Greeks = 5
    Profile = 7
    Summary = 9
    Errors = 99


class SessionState(Enum):
    """Defines possible states for a trading session."""

    INITIALIZING = "initializing"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    DISCONNECTED = "disconnected"
    ERROR = "error"


# Connection configurations
@dataclass
class ConnectionConfig:
    """Configuration for connection management."""

    keepalive_timeout: int = 60
    reconnect_attempts: int = 3
    reconnect_delay: int = 5
    max_queue_size: int = 1000


@dataclass
class ChannelSpecification:
    """Defines the specification for a market data channel."""

    name: str
    channel: Channels
    event_type: Type[TradeEvent | QuoteEvent | GreeksEvent | ProfileEvent | SummaryEvent]
    fields: List[str]
    description: str


class ChannelSpecs:
    """Central registry of channel specifications."""

    @classmethod
    def __iter__(cls):
        return (
            value
            for name, value in vars(cls).items()
            if isinstance(value, ChannelSpecification) and not name.startswith("_")
        )

    TRADES = ChannelSpecification(
        name="Trade",
        channel=Channels.Trades,
        event_type=TradeEvent,
        fields=["eventSymbol", "price", "dayVolume", "size"],
        description="Real-time trade execution data",
    )

    QUOTES = ChannelSpecification(
        name="Quote",
        channel=Channels.Quotes,
        event_type=QuoteEvent,
        fields=["eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize"],
        description="Real-time quote updates",
    )

    GREEKS = ChannelSpecification(
        name="Greeks",
        channel=Channels.Greeks,
        event_type=GreeksEvent,
        fields=["eventSymbol", "volatility", "delta", "gamma", "theta", "rho", "vega"],
        description="Option greek calculations",
    )

    PROFILE = ChannelSpecification(
        name="Profile",
        channel=Channels.Profile,
        event_type=ProfileEvent,
        fields=[
            "eventSymbol",
            "description",
            "shortSaleRestriction",
            "tradingStatus",
            "statusReason",
            "haltStartTime",
            "haltEndTime",
            "highLimitPrice",
            "lowLimitPrice",
            "high52WeekPrice",
            "low52WeekPrice",
        ],
        description="Profile",  # TODO Update
    )

    SUMMARY = ChannelSpecification(
        name="Summary",
        channel=Channels.Summary,
        event_type=SummaryEvent,
        fields=[
            "eventSymbol",
            "openInterest",
            "dayOpenPrice",
            "dayHighPrice",
            "dayLowPrice",
            "prevDayClosePrice",
        ],
        description="Summary",  # TODO Update
    )

    @classmethod
    def get_spec(cls, channel: Channels) -> ChannelSpecification:
        """Get the specification for a given channel."""
        return getattr(cls, channel.name.upper())
