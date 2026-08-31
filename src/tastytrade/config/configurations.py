# central local for session configurations

from dataclasses import dataclass
from typing import List

from tastytrade.config.enumerations import Channels, EventTypes


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
    # Concurrent in-flight candle subscriptions cap. dxFeed retail rejects
    # bursts past ~20 with "subscription size too big"; 18 leaves headroom.
    candle_subscription_concurrency: int = 18
    reconnect_attempts: int = 3  # for later use
    reconnect_delay: int = 5  # for later use


@dataclass
class ChannelSpecification:
    """Defines the specification for a market data channel."""

    type: str
    channel: Channels
    event_type: EventTypes
    description: str
    # FEED_SETUP acceptAggregationPeriod for this channel: the minimum
    # seconds between updates dxFeed sends per subscription. 0.1 is the
    # practical firehose; candle channels are tiered (TT-164) because only
    # the traded intervals need sub-second forming-bar repaints.
    aggregation_period: float = 0.1

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
        description="Historical and real-time candle data (conflated tier)",
        aggregation_period=1.0,
    ),
    # Fast candle tier (TT-164): subscriptions in the configured fast pool
    # (CANDLE_FAST_POOL, default SPX 1m/5m) ride this channel at full rate.
    # The dxFeed event type is still "Candle" — only the channel differs.
    Channels.CandleFast: ChannelSpecification(
        type=Channels.Candle.name,
        channel=Channels.CandleFast,
        event_type=EventTypes.Candle,
        description="Firehose candle data for the configured fast pool",
        aggregation_period=0.1,
    ),
}
