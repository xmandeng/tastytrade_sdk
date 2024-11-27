import asyncio
import json
import logging
from asyncio import Semaphore
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from tastytrade.sessions.messaging import Channels
from tastytrade.sessions.sockets import WebSocketManager

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)

FEED_SPECS = {
    # "Trade": ["eventSymbol", "price", "dayVolume", "size"],
    "Quote": [
        "eventSymbol",
        "bidPrice",
        "askPrice",
        "bidSize",
        "askSize",
    ],
    # "Greeks": [
    #     "eventSymbol",
    #     "volatility",
    #     "delta",
    #     "gamma",
    #     "theta",
    #     "rho",
    #     "vega",
    # ],
    # "Profile": [
    #     "eventSymbol",
    #     "description",
    #     "shortSaleRestriction",
    #     "tradingStatus",
    #     "statusReason",
    #     "haltStartTime",
    #     "haltEndTime",
    #     "highLimitPrice",
    #     "lowLimitPrice",
    #     "high52WeekPrice",
    #     "low52WeekPrice",
    # ],
    # "Summary": [
    #     "eventSymbol",
    #     "openInterest",
    #     "dayOpenPrice",
    #     "dayHighPrice",
    #     "dayLowPrice",
    #     "prevDayClosePrice",
    # ],
}

FEED_SETUP = {
    "type": "FEED_SETUP",
    "acceptAggregationPeriod": 0.1,
    "acceptDataFormat": "COMPACT",
    "acceptEventFields": FEED_SPECS,
}
SUBSCRIPTION_REQUEST = {
    "type": "FEED_SUBSCRIPTION",
    "reset": True,
    "add": [
        # {"type": "Trade", "symbol": "BTC/USD:CXTALP"},
        # {"type": "Trade", "symbol": "SPY"},
        # {"type": "Profile", "symbol": "BTC/USD:CXTALP"},
        # {"type": "Profile", "symbol": "SPY"},
        # {"type": "Summary", "symbol": "BTC/USD:CXTALP"},
        # {"type": "Summary", "symbol": "SPY"},
        # {"type": "Greeks", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5990"},
        # {"type": "Greeks", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5980"},
        # {"type": "Greeks", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5970"},
        {"type": "Quote", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5990"},
        {"type": "Quote", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5980"},
        {"type": "Quote", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5970"},
        {"type": "Quote", "symbol": "SPX"},
        {"type": "Quote", "symbol": "BTC/USD:CXTALP"},
    ],
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

    async def setup_feed(self, channel: Channels, request: dict[str, Any] = FEED_SETUP):
        request = request | {"channel": channel.value}
        await asyncio.wait_for(self.websocket.send(json.dumps(request)), timeout=5)

    async def subscribe_to_feed(
        self, channel: Channels, request: dict[str, Any] = SUBSCRIPTION_REQUEST
    ):
        request = request | {"channel": channel.value}
        async with self.subscription_semaphore:
            await asyncio.wait_for(
                self.websocket.send(json.dumps(request)),
                timeout=5,
            )
