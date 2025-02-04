import asyncio
import json
import logging
from asyncio import Semaphore
from typing import List

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
    instance = None
    queues: dict[int, asyncio.Queue]

    session: AsyncSessionHandler
    websocket: ClientConnection
    subscription_semaphore: Semaphore

    listener_task: asyncio.Task

    @classmethod
    def get_instance(cls):
        return cls.instance

    def __new__(cls):
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(
        self,
    ):
        config = DXLinkConfig()
        self.queues = {channel.value: asyncio.Queue() for channel in Channels}
        self.subscription_semaphore = Semaphore(config.max_subscriptions)
        self.keepalive_stop = asyncio.Event()

    async def __aenter__(self, credentials: Credentials):
        await self.open(credentials)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def connect(self, credentials: Credentials):
        asyncio.create_task(self.open(credentials))

    async def open(self, credentials: Credentials):
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

    async def start_listener(self):
        self.listener_task = asyncio.create_task(self.socket_listener(), name="websocket_listener")

        self.keepalive_task = asyncio.create_task(
            self.send_keepalives(), name="websocket_keepalive"
        )

    async def start_router(self):
        self.router = MessageDispatcher(self)

    async def socket_listener(self):
        """Listen for websocket messages using async for pattern."""
        try:
            async for message in self.websocket:
                logger.debug("%s", message)

                try:
                    event = EventReceivedModel(**json.loads(message))
                    channel = event.channel if event.type == "FEED_DATA" else 0
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {e}\n{message}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}\n{message}")

                try:
                    await self.queues[channel].put(event.fields)
                except asyncio.QueueFull:
                    logger.warning(f"Queue {channel} is full - dropping message")

        except asyncio.CancelledError:
            logger.info("Websocket listener stopped")
        except Exception as e:
            logger.error(f"Websocket listener error: {e}")

    async def send_keepalives(self):
        """Send keepalive messages every 30 seconds."""
        try:
            while True:
                await asyncio.sleep(30)  # This properly yields to event loop
                await self.websocket.send(KeepaliveModel().model_dump_json())
                logger.debug("Keepalive sent from client")
        except asyncio.CancelledError:
            logger.info("Keepalive stopped")
        except Exception as e:
            logger.error("Error sending keepalive: %s", e)

    async def setup_connection(self):
        request = SetupModel()
        await asyncio.wait_for(self.websocket.send(request.model_dump_json()), timeout=5)

    async def authorize_connection(self):
        request = AuthModel(token=self.session.session.headers["token"])
        await asyncio.wait_for(self.websocket.send(request.model_dump_json()), timeout=5)

    async def open_channels(self):
        for channel in Channels:
            if channel == Channels.Control:
                continue

            request = OpenChannelModel(channel=channel.value).model_dump_json()
            await asyncio.wait_for(self.websocket.send(request), timeout=5)

    async def setup_feeds(self) -> None:
        for specification in CHANNEL_SPECS.values():
            if specification.channel == Channels.Control:
                continue

            request = FeedSetupModel(
                acceptEventFields={specification.type: specification.fields},
                channel=specification.channel.value,
            ).model_dump_json()

            await asyncio.wait_for(
                self.websocket.send(request),
                timeout=5,
            )

    async def subscribe(self, symbols: List[str]):
        for specification in CHANNEL_SPECS.values():
            if specification.channel == Channels.Control:
                continue

            request = SubscriptionRequest(
                channel=specification.channel.value,
                add=[AddItem(type=specification.type, symbol=symbol) for symbol in symbols],
            ).model_dump_json()

            async with self.subscription_semaphore:
                await asyncio.wait_for(
                    self.websocket.send(request),
                    timeout=5,
                )

    async def subscribe_to_candles(self, request: CandleSubscriptionRequest):
        """Subscribe to candle data for a symbol.

        Args:
            request: CandleSubscriptionRequest containing symbol and interval
        """
        subscription = SubscriptionRequest(
            channel=Channels.Candle.value,
            add=[
                AddCandleItem(
                    type=Channels.Candle.name,
                    symbol=f"{request.symbol}{{={request.interval}}}",
                    fromTime=request.from_time,
                )
            ],
        ).model_dump_json()

        async with self.subscription_semaphore:
            await asyncio.wait_for(
                self.websocket.send(subscription),
                timeout=5,
            )

        # Send configuration for the candle feed
        feed_setup = FeedSetupModel(
            acceptEventFields={Channels.Candle.name: CHANNEL_SPECS[Channels.Candle].fields},
            channel=Channels.Candle.value,
        ).model_dump_json()

        await asyncio.wait_for(
            self.websocket.send(feed_setup),
            timeout=5,
        )

    async def close(self):
        if not hasattr(self, "websocket"):
            logger.warning("Websocket - No active connection to close")
            return

        tasks_to_cancel = [
            ("Listener", getattr(self, "listener_task", None)),
            ("Keepalive", getattr(self, "keepalive_task", None)),
        ]

        await asyncio.gather(
            *[self.cancel_tasks(name, task) for name, task in tasks_to_cancel if task is not None]
        )

        await self.websocket.close()
        await self.router.close()
        logger.info("Websocket closed")

        self.websocket = None

    async def cancel_tasks(self, name: str, task: asyncio.Task):
        try:
            task.cancel()
            await task
            logger.info(f"{name} task cancelled")
        except asyncio.CancelledError:
            logger.info(f"{name} task was cancelled")
            logger.info(f"{name} task was cancelled")
