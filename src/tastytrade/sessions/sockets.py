import asyncio
import json
import logging
from asyncio import Semaphore
from datetime import datetime
from types import TracebackType
from typing import List, Optional, Type

from injector import singleton
from websockets.asyncio.client import ClientConnection, connect

from tastytrade.sessions import Credentials
from tastytrade.sessions.configurations import CHANNEL_SPECS, DXLinkConfig
from tastytrade.sessions.enumerations import Channels
from tastytrade.sessions.messaging import MessageDispatcher
from tastytrade.sessions.models import (
    AddCandleItem,
    AddItem,
    AuthModel,
    CancelCandleItem,
    CancelCandleSubscriptionRequest,
    CancelItem,
    CandleSubscriptionRequest,
    EventReceivedModel,
    FeedSetupModel,
    KeepaliveModel,
    OpenChannelModel,
    SetupModel,
    SubscriptionRequest,
)
from tastytrade.sessions.requests import AsyncSessionHandler

logger = logging.getLogger(__name__)


@singleton
class DXLinkManager:
    """Responsible for managing the DXLink connection and the channels. It also handles the subscription and unsubscription to the channels.

    dxLink Websocket Docs: https://demo.dxfeed.com/dxlink-ws/debug/#/protocol
    """

    instance: Optional["DXLinkManager"] = None
    queues: dict[int, asyncio.Queue]

    session: Optional[AsyncSessionHandler] = None
    websocket: Optional[ClientConnection] = None
    subscription_semaphore: Semaphore

    listener_task: Optional[asyncio.Task] = None
    keepalive_task: Optional[asyncio.Task] = None
    router: Optional[MessageDispatcher] = None

    @classmethod
    def get_instance(cls) -> Optional["DXLinkManager"]:
        return cls.instance

    def __new__(cls: Type["DXLinkManager"]) -> "DXLinkManager":
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(self) -> None:
        config = DXLinkConfig()
        self.queues = {channel.value: asyncio.Queue() for channel in Channels}
        self.subscription_semaphore = Semaphore(config.max_subscriptions)
        self.keepalive_stop = asyncio.Event()

    async def __aenter__(self, credentials: Credentials) -> "DXLinkManager":
        await self.open(credentials)
        return self

    async def __aexit__(
        self,
        exc_type: Optional[BaseException],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    def connect(self, credentials: Credentials) -> None:
        asyncio.create_task(self.open(credentials))

    async def open(self, credentials: Credentials) -> None:
        self.session = await AsyncSessionHandler.create(credentials)
        self.websocket = await connect(self.session.session.headers["dxlink-url"])

        try:
            await self.setup_connection()
            await self.authorize_connection()
            await self.open_channels()
            await self.setup_feeds()
            await self.start_listener()
            await self.start_router()

        except Exception as e:
            logger.error("Error while opening connection: %s", e)
            await self.websocket.close()
            raise e

    async def start_listener(self) -> None:
        self.listener_task = asyncio.create_task(self.socket_listener(), name="websocket_listener")

        self.keepalive_task = asyncio.create_task(
            self.send_keepalives(), name="websocket_keepalive"
        )

    async def start_router(self) -> None:
        self.router = MessageDispatcher(self)

    async def socket_listener(self) -> None:
        """Listen for websocket messages using async for pattern."""
        assert self.websocket is not None, "websocket should be initialized"
        try:
            async for message in self.websocket:
                logger.debug("%s", message)

                try:
                    event = EventReceivedModel(**json.loads(message))
                    channel = event.channel if event.type == "FEED_DATA" else 0
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse message: %s\n%s", e, message)
                except Exception as e:
                    logger.error("Error processing message: %s\n%s", e, message)

                try:
                    await self.queues[channel].put(event.fields)
                except asyncio.QueueFull:
                    logger.warning(f"Queue {channel} is full - dropping message")

        except asyncio.CancelledError:
            logger.info("Websocket listener stopped")
        except Exception as e:
            logger.error(f"Websocket listener error: {e}")

    async def send_keepalives(self) -> None:
        """Send keepalive messages every 30 seconds."""
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        try:
            while True:
                await asyncio.sleep(30)  # This properly yields to event loop
                await ws.send(KeepaliveModel().model_dump_json())
                logger.debug("Keepalive sent from client")
        except asyncio.CancelledError:
            logger.info("Keepalive stopped")
        except Exception as e:
            logger.error("Error sending keepalive: %s", e)

    async def setup_connection(self) -> None:
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        request = SetupModel()
        await asyncio.wait_for(ws.send(request.model_dump_json()), timeout=5)

    async def authorize_connection(self) -> None:
        assert self.session is not None, "session should be initialized"
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        request = AuthModel(token=self.session.session.headers["token"])
        await asyncio.wait_for(ws.send(request.model_dump_json()), timeout=5)

    async def open_channels(self) -> None:
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        for channel in Channels:
            if channel == Channels.Control:
                continue

            request = OpenChannelModel(channel=channel.value).model_dump_json()
            await asyncio.wait_for(ws.send(request), timeout=5)

    async def setup_feeds(self) -> None:
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        for specification in CHANNEL_SPECS.values():
            if specification.channel == Channels.Control:
                continue

            request = FeedSetupModel(
                acceptEventFields={specification.type: specification.fields},
                channel=specification.channel.value,
            ).model_dump_json()

            await asyncio.wait_for(ws.send(request), timeout=5)

    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to data for a list of symbols.

        request format:
        {
            "type": "FEED_SUBSCRIPTION",
            "channel": 3,
            "reset": true,
            "add": [
                {"type": "Trade","symbol": "BTC/USD:CXTALP"},
                {"type": "Trade","symbol": "SPY"},
            ]
        }

        response format: {
            "type": "FEED_DATA",
            "channel": 3,
            "data": [
                "Trade",
                [
                    "Trade","SPY",559.36,1.3743299E7,100.0,
                    "Trade","BTC/USD:CXTALP",58356.71,"NaN","NaN"
                ]
            ]
        }
        """
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        for specification in CHANNEL_SPECS.values():
            if specification.channel in [Channels.Control, Channels.Candle]:
                continue

            subscription = SubscriptionRequest(
                channel=specification.channel.value,
                add=[AddItem(type=specification.type, symbol=symbol) for symbol in symbols],
            ).model_dump_json()

            async with self.subscription_semaphore:
                await asyncio.wait_for(ws.send(subscription), timeout=5)

    async def unsubscribe(self, symbols: List[str]) -> None:
        """Subscribe to data for a list of symbols.

        request format:
        {
            "type": "FEED_SUBSCRIPTION",
            "channel": 3,
            "remove": [
                {"type": "Trade","symbol": "BTC/USD:CXTALP"},
                {"type": "Trade","symbol": "SPY"},
            ]
        }
        """
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        for specification in CHANNEL_SPECS.values():
            if specification.channel in [Channels.Control, Channels.Candle]:
                continue

            cancellation = SubscriptionRequest(
                channel=specification.channel.value,
                remove=[CancelItem(type=specification.type, symbol=symbol) for symbol in symbols],
            ).model_dump_json()

            async with self.subscription_semaphore:
                await asyncio.wait_for(ws.send(cancellation), timeout=5)

        for symbol in symbols:
            logger.info("Unsubscribed: %s", symbol)

    async def subscribe_to_candles(
        self,
        symbol: str,
        interval: str,
        from_time: int = int(datetime.now().timestamp() * 1000),
        to_time: Optional[int] = None,
    ) -> None:
        """Subscribe to candle data for a symbol.

        Args:
            symbol: The symbol to subscribe to
            interval: The interval of the candles to subscribe to
            from_time: The start time of the candles to subscribe to

        """
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket

        request: CandleSubscriptionRequest = CandleSubscriptionRequest(
            symbol=symbol,
            interval=interval,
            from_time=from_time,
            to_time=to_time,
        )

        subscription = SubscriptionRequest(
            channel=Channels.Candle.value,
            add=[
                AddCandleItem(
                    type=Channels.Candle.name,
                    symbol=request.formatted,
                    fromTime=request.from_time,
                    toTime=request.to_time,
                )
            ],
        ).model_dump_json()

        async with self.subscription_semaphore:
            await asyncio.wait_for(ws.send(subscription), timeout=5)

    async def unsubscribe_to_candles(self, *, symbol: str, interval: str) -> None:
        """Subscribe to candle data for a symbol.

        Args:
            request: CandleSubscriptionRequest containing symbol and interval
        """
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket
        request: CancelCandleSubscriptionRequest = CancelCandleSubscriptionRequest(
            symbol=symbol,
            interval=interval,
        )

        cancellation = SubscriptionRequest(
            channel=Channels.Candle.value,
            remove=[
                CancelCandleItem(
                    type=Channels.Candle.name,
                    symbol=f"{request.symbol}{{={request.interval}}}",
                )
            ],
        ).model_dump_json()

        async with self.subscription_semaphore:
            await asyncio.wait_for(ws.send(cancellation), timeout=5)

        logger.info("Unsubscribed Candlesticks: %s{=%s}", symbol, interval)

    async def close(self) -> None:
        if self.websocket is None:
            logger.warning("Websocket - No active connection to close")
            return

        tasks_to_cancel = [
            ("Listener", self.listener_task),
            ("Keepalive", self.keepalive_task),
        ]

        await asyncio.gather(
            *[self.cancel_tasks(name, task) for name, task in tasks_to_cancel if task is not None]
        )

        # Close websocket connection
        if self.websocket is not None:
            ws = self.websocket
            await ws.close()
            self.websocket = None

        # Close message router
        if self.router is not None:
            r = self.router
            await r.close()
            self.router = None

        # Close session
        if self.session is not None:
            s = self.session
            await s.close()
            self.session = None

        logger.info("Connection closed and cleaned up")

    async def cancel_tasks(self, name: str, task: asyncio.Task) -> None:
        try:
            task.cancel()
            await task
            logger.info(f"{name} task cancelled")
        except asyncio.CancelledError:
            logger.info(f"{name} task was cancelled")
