import asyncio
import json
import logging
from asyncio import Semaphore
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any, Dict, List, Optional

from injector import singleton
from websockets.asyncio.client import ClientConnection, connect

from tastytrade.config.configurations import CHANNEL_SPECS, DXLinkConfig
from tastytrade.config.enumerations import Channels
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.connections.routing import MessageRouter
from tastytrade.connections.subscription import (
    InMemorySubscriptionStore,
    SubscriptionStore,
)
from tastytrade.messaging.models.messages import (
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
from tastytrade.utils.helpers import parse_candle_symbol

logger = logging.getLogger(__name__)


@dataclass
class SubscriptionInfo:
    """Track information about a subscription."""

    symbol: str
    subscribe_time: datetime
    interval: Optional[str] = None  # None for regular feed subscriptions
    active: bool = True
    last_update: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)


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
    router: Optional[MessageRouter] = None

    def __new__(
        cls,
        credentials: Optional[Credentials] = None,
        subscription_store: Optional[SubscriptionStore] = None,
    ) -> "DXLinkManager":
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(
        self,
        credentials: Optional[Credentials] = None,
        subscription_store: Optional[SubscriptionStore] = None,
    ) -> None:
        if not hasattr(self, "initialized"):
            config = DXLinkConfig()
            self.queues = {channel.value: asyncio.Queue() for channel in Channels}
            self.subscription_semaphore = Semaphore(config.max_subscriptions)
            self.keepalive_stop = asyncio.Event()
            self.credentials = credentials

            # Initialize subscription tracking
            self.active_subscriptions: Dict[str, SubscriptionInfo] = {}
            self.subscription_lock = asyncio.Lock()
            self.subscription_store: SubscriptionStore = (
                subscription_store or InMemorySubscriptionStore()
            )

            self.initialized = True

    async def __aenter__(self) -> "DXLinkManager":
        if self.credentials:
            await self.open(self.credentials)
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
            await self.subscription_store.initialize()
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
        self.listener_task = asyncio.create_task(
            self.socket_listener(), name="websocket_listener"
        )

        self.keepalive_task = asyncio.create_task(
            self.send_keepalives(), name="websocket_keepalive"
        )

    async def start_router(self) -> None:
        self.router = MessageRouter(self)

    async def socket_listener(self) -> None:
        """Listen for websocket messages using async for pattern."""
        assert self.websocket is not None, "websocket should be initialized"
        try:
            async for message in self.websocket:
                logger.debug("%s", message)

                try:
                    event = EventReceivedModel(**json.loads(message))
                    channel = event.channel if event.type == "FEED_DATA" else 0

                    # Update subscription status if it's a feed event
                    if event.type == "FEED_DATA" and "eventSymbol" in event.fields:
                        await self.update_subscription_status(
                            event.fields["eventSymbol"], event.fields
                        )

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

    async def track_subscription(
        self, symbol: str, metadata: Optional[Dict[Any, Any]] = None
    ) -> None:
        """Track a new subscription."""
        await self.subscription_store.add_subscription(symbol, metadata)
        logger.info(f"Added subscription: {symbol}")

    async def remove_subscription(self, symbol: str) -> None:
        """Remove subscription tracking."""
        await self.subscription_store.remove_subscription(symbol)
        logger.info(f"Marked subscription {symbol} as inactive")

    async def get_active_subscriptions(self) -> Dict:
        """Get all active subscriptions."""
        return await self.subscription_store.get_active_subscriptions()

    async def update_subscription_status(self, symbol: str, data: Dict) -> None:
        """Update last update time and metadata for a subscription."""
        await self.subscription_store.update_subscription_status(symbol, data)

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

        # Track new subscriptions
        for symbol in symbols:
            await self.track_subscription(symbol)

        for specification in CHANNEL_SPECS.values():
            if specification.channel in [Channels.Control, Channels.Candle]:
                continue

            subscription = SubscriptionRequest(
                channel=specification.channel.value,
                add=[
                    AddItem(type=specification.type, symbol=symbol)
                    for symbol in symbols
                ],
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

        # Remove subscription tracking
        for symbol in symbols:
            await self.remove_subscription(symbol)

        for specification in CHANNEL_SPECS.values():
            if specification.channel in [Channels.Control, Channels.Candle]:
                continue

            cancellation = SubscriptionRequest(
                channel=specification.channel.value,
                remove=[
                    CancelItem(type=specification.type, symbol=symbol)
                    for symbol in symbols
                ],
            ).model_dump_json()

            async with self.subscription_semaphore:
                await asyncio.wait_for(ws.send(cancellation), timeout=5)

        for symbol in symbols:
            logger.info("Unsubscribed: %s", symbol)

    async def subscribe_to_candles(
        self,
        symbol: str,
        interval: str,
        from_time: datetime,
        to_time: Optional[datetime] = None,
    ) -> None:
        """Subscribe to candle data for a symbol."""
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket

        request: CandleSubscriptionRequest = CandleSubscriptionRequest(
            symbol=symbol,
            interval=interval,
            from_time=from_time,  # type: ignore[arg-type]
            to_time=to_time,  # type: ignore[arg-type]
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

        # Track candle subscription
        await self.track_subscription(request.formatted)

    async def unsubscribe_to_candles(self, event_symbol: str) -> None:
        """Subscribe to candle data for a symbol."""
        assert self.websocket is not None, "websocket should be initialized"
        ws = self.websocket

        symbol, interval = parse_candle_symbol(event_symbol)
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

        # Remove candle subscription cache
        await self.remove_subscription(event_symbol)

        logger.info("Unsubscribed Candlesticks: %s", event_symbol)

    async def close(self) -> None:
        if self.websocket is None:
            logger.warning("Websocket - No active connection to close")
            return

        tasks_to_cancel = [
            ("Listener", self.listener_task),
            ("Keepalive", self.keepalive_task),
        ]

        await asyncio.gather(
            *[
                self.cancel_tasks(name, task)
                for name, task in tasks_to_cancel
                if task is not None
            ]
        )

        # Reset active subscriptions
        self.active_subscriptions = {}

        # Reset Initialized
        self.initialized = False

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
