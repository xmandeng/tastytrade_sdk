# central local for session configurations

from dataclasses import dataclass
from typing import List

from tastytrade.sessions.enumerations import Channels, EventTypes


# Connection configurations
@dataclass
class ConnectionConfig:
    """Configuration for connection management."""

    keepalive_timeout: int = 60
    reconnect_attempts: int = 3
    reconnect_delay: int = 5
    max_queue_size: int = 1000


@dataclass
class DXLinkConfig:
    keepalive_timeout: int = 60
    version: str = "0.1-DXF-JS/0.3.0"
    channel_assignment: int = 1
    max_subscriptions: int = 20
    reconnect_attempts: int = 3  # for later use
    reconnect_delay: int = 5  # for later use


@dataclass
class ChannelSpecification:
    """Defines the specification for a market data channel."""

    type: str
    channel: Channels
    event_type: EventTypes
    fields: List[str]
    description: str


trade_specs = ChannelSpecification(
    type="Trade",
    channel=Channels.Trades,
    event_type=EventTypes.Trades,
    fields=["eventSymbol", "price", "dayVolume", "size"],
    description="Real-time trade execution data",
)

quote_specs = ChannelSpecification(
    type="Quote",
    channel=Channels.Quotes,
    event_type=EventTypes.Quotes,
    fields=["eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize"],
    description="Real-time quote updates",
)

greeks_specs = ChannelSpecification(
    type="Greeks",
    channel=Channels.Greeks,
    event_type=EventTypes.Greeks,
    fields=["eventSymbol", "volatility", "delta", "gamma", "theta", "rho", "vega"],
    description="Option greeks values",
)

profile_specs = ChannelSpecification(
    type="Profile",
    channel=Channels.Profile,
    event_type=EventTypes.Profile,
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

summary_specs = ChannelSpecification(
    type="Summary",
    channel=Channels.Summary,
    event_type=EventTypes.Summary,
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

control_specs = ChannelSpecification(
    type="Control",
    channel=Channels.Control,
    event_type=EventTypes.Control,
    fields=[],
    description="Not Used -- Control plane events",
)


CHANNEL_SPECS = {
    Channels.Trades: trade_specs,
    Channels.Quotes: quote_specs,
    Channels.Greeks: greeks_specs,
    Channels.Profile: profile_specs,
    Channels.Summary: summary_specs,
    Channels.Control: control_specs,
}
