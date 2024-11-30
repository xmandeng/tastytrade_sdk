import asyncio
import logging
from asyncio import Semaphore
from dataclasses import dataclass
from typing import Any, List, Optional

import tastytrade.sessions.types as types
from tastytrade.sessions.configurations import Channels, ChannelSpecs

# from tastytrade.sessions.messaging import Channels
from tastytrade.sessions.sockets import WebSocketManager

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)


CHANNEL_SPECS: dict[Channels, dict[str, list[str]]] = {
    Channels.Trades: {"Trade": ["eventSymbol", "price", "dayVolume", "size"]},
    Channels.Quotes: {
        "Quote": [
            "eventSymbol",
            "bidPrice",
            "askPrice",
            "bidSize",
            "askSize",
        ],
    },
    Channels.Greeks: {
        "Greeks": [
            "eventSymbol",
            "volatility",
            "delta",
            "gamma",
            "theta",
            "rho",
            "vega",
        ]
    },
    Channels.Profile: {
        "Profile": [
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
    },
    Channels.Summary: {
        "Summary": [
            "eventSymbol",
            "openInterest",
            "dayOpenPrice",
            "dayHighPrice",
            "dayLowPrice",
            "prevDayClosePrice",
        ],
    },
}


@dataclass
class DXLinkConfig:
    keepalive_timeout: int = 60
    version: str = "0.1-DXF-JS/0.3.0"
    channel_assignment: int = 1
    max_subscriptions: int = 100
    reconnect_attempts: int = 3  # for later use
    reconnect_delay: int = 5  # for later use


class DXLinkClient:

    def __init__(
        self,
        websocket_manager: WebSocketManager,
        config: Optional[DXLinkConfig] = None,
    ):
        self.websocket = websocket_manager.websocket
        self.queue_manager = websocket_manager.queue_manager
        config = config or DXLinkConfig()

        self.subscription_semaphore = Semaphore(config.max_subscriptions)

    async def setup_feeds(self) -> None:
        for feed in ChannelSpecs():
            request = generate_feed_setup_request(feed.channel)
            await asyncio.wait_for(
                self.websocket.send(request),
                timeout=5,
            )

    async def subscribe_to_feeds(self, symbols: List[str]):
        for feed in ChannelSpecs():
            request = generate_subscription_request(feed.channel, symbols)
            async with self.subscription_semaphore:
                await asyncio.wait_for(
                    self.websocket.send(request),
                    timeout=5,
                )


def generate_feed_setup_request(channel: Channels) -> str:
    request = types.FeedSetupModel(
        acceptEventFields=CHANNEL_SPECS[channel],
        channel=channel.value,
    )
    return request.model_dump_json()


def generate_subscription_request(channel: Channels, symbols: List[str]) -> str:
    channel_type = ChannelSpecs.get_spec(channel).name
    add_items = [types.AddItem(type=channel_type, symbol=symbol) for symbol in symbols]
    request = types.SubscriptionRequest(channel=channel.value, add=add_items)
    return request.model_dump_json()
