# central local for session configurations

from dataclasses import dataclass
from typing import List

from tastytrade.sessions.enumerations import Channels, EventTypes


# TODO - Get rid of this
# ? Why do I need to exclude timestamp?
def get_fields(event_type: EventTypes) -> List[str]:
    return [field for field in event_type.value.model_fields if field != "timestamp"]


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


CHANNEL_SPECS = {
    Channels.Trade: ChannelSpecification(
        type=Channels.Trade.name,
        channel=Channels.Trade,
        event_type=EventTypes.Trade,
        fields=get_fields(EventTypes.Trade),
        description="Real-time trade execution data",
    ),
    Channels.Quote: ChannelSpecification(
        type=Channels.Quote.name,
        channel=Channels.Quote,
        event_type=EventTypes.Quote,
        fields=get_fields(EventTypes.Quote),
        description="Real-time quote updates",
    ),
    Channels.Greeks: ChannelSpecification(
        type=Channels.Greeks.name,
        channel=Channels.Greeks,
        event_type=EventTypes.Greeks,
        fields=get_fields(EventTypes.Greeks),
        description="Option greeks values",
    ),
    Channels.Profile: ChannelSpecification(
        type=Channels.Profile.name,
        channel=Channels.Profile,
        event_type=EventTypes.Profile,
        fields=get_fields(EventTypes.Profile),
        description="Profile",  # TODO Update
    ),
    Channels.Summary: ChannelSpecification(
        type=Channels.Summary.name,
        channel=Channels.Summary,
        event_type=EventTypes.Summary,
        fields=get_fields(EventTypes.Summary),
        description="Summary",  # TODO Update
    ),
    Channels.Control: ChannelSpecification(
        type=Channels.Control.name,
        channel=Channels.Control,
        event_type=EventTypes.Control,
        fields=[],
        description="Not Used -- Control plane events",
    ),
}
