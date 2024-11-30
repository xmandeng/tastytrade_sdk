import asyncio
import logging
from asyncio import Semaphore
from dataclasses import dataclass
from typing import Any, List, Optional

import tastytrade.sessions.types as types
from tastytrade.sessions.configurations import ChannelSpecification, ChannelSpecs

# from tastytrade.sessions.messaging import Channels
from tastytrade.sessions.sockets import WebSocketManager

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)


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
            request = generate_feed_setup_request(feed)
            await asyncio.wait_for(
                self.websocket.send(request),
                timeout=5,
            )

    async def subscribe_to_feeds(self, symbols: List[str]):
        for feed in ChannelSpecs():
            request = generate_subscription_request(feed, symbols)
            async with self.subscription_semaphore:
                await asyncio.wait_for(
                    self.websocket.send(request),
                    timeout=5,
                )


def generate_feed_setup_request(feed: ChannelSpecification) -> str:
    request = types.FeedSetupModel(
        acceptEventFields={feed.type: feed.fields},
        channel=feed.channel.value,
    )
    return request.model_dump_json()


def generate_subscription_request(feed: ChannelSpecification, symbols: List[str]) -> str:
    add_items = [types.AddItem(type=feed.type, symbol=symbol) for symbol in symbols]
    request = types.SubscriptionRequest(channel=feed.channel.value, add=add_items)
    return request.model_dump_json()
