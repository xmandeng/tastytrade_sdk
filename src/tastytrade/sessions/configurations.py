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
    description: str

    @property
    def fields(self) -> List[str]:
        if self.event_type == EventTypes.Control:
            return []
        return list(self.event_type.value.model_fields.keys())


CHANNEL_SPECS = {
    Channels.Trade: ChannelSpecification(
        type=Channels.Trade.name,
        channel=Channels.Trade,
        event_type=EventTypes.Trade,
        description="Real-time trade execution data",
    ),
    Channels.Quote: ChannelSpecification(
        type=Channels.Quote.name,
        channel=Channels.Quote,
        event_type=EventTypes.Quote,
        description="Real-time quote updates",
    ),
    Channels.Greeks: ChannelSpecification(
        type=Channels.Greeks.name,
        channel=Channels.Greeks,
        event_type=EventTypes.Greeks,
        description="Option greeks values",
    ),
    Channels.Profile: ChannelSpecification(
        type=Channels.Profile.name,
        channel=Channels.Profile,
        event_type=EventTypes.Profile,
        description="Most recent information that is available about the traded security",
    ),
    Channels.Summary: ChannelSpecification(
        type=Channels.Summary.name,
        channel=Channels.Summary,
        event_type=EventTypes.Summary,
        description="Snapshot about the trading session including session highs, lows, etc",
    ),
    Channels.Control: ChannelSpecification(
        type=Channels.Control.name,
        channel=Channels.Control,
        event_type=EventTypes.Control,
        description="Not Used -- Control plane events",
    ),
    Channels.Candle: ChannelSpecification(
        type=Channels.Candle.name,
        channel=Channels.Candle,
        event_type=EventTypes.Candle,
        description="Historical and real-time candle data",
    ),
}
