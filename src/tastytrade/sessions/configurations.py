# central local for session configurations

from dataclasses import dataclass
from typing import List, Optional

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
class ChannelSpecification:
    """Defines the specification for a market data channel."""

    type: str
    channel: Channels
    event_type: EventTypes
    fields: List[str]
    description: str


class ChannelSpecs:
    """Central registry of channel specifications.

    TODO: Pytest - check `channel_spec.fields` matches `eventModel.fields`
    """

    @classmethod
    def __iter__(cls):
        """Iterate over non-control channels: TRADES -> QUOTES -> GREEKS -> PROFILE -> SUMMARY -> etc.

        TODO: Cleanup channel specs
        """
        return (
            value
            for name, value in vars(cls).items()
            if isinstance(value, ChannelSpecification) and name != "control"
        )

    trades = ChannelSpecification(
        type="Trade",
        channel=Channels.Trades,
        event_type=EventTypes.Trades,
        fields=["eventSymbol", "price", "dayVolume", "size"],
        description="Real-time trade execution data",
    )

    quotes = ChannelSpecification(
        type="Quote",
        channel=Channels.Quotes,
        event_type=EventTypes.Quotes,
        fields=["eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize"],
        description="Real-time quote updates",
    )

    greeks = ChannelSpecification(
        type="Greeks",
        channel=Channels.Greeks,
        event_type=EventTypes.Greeks,
        fields=["eventSymbol", "volatility", "delta", "gamma", "theta", "rho", "vega"],
        description="Option greeks values",
    )

    profile = ChannelSpecification(
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

    summary = ChannelSpecification(
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

    control = ChannelSpecification(
        type="Control",
        channel=Channels.Control,
        event_type=EventTypes.Control,
        fields=[],
        description="Not Used -- Control plane events",
    )

    @classmethod
    def get_spec(cls, channel: Channels) -> Optional[ChannelSpecification]:
        """Get the specification for a given channel."""
        return getattr(cls, channel.name.lower())
