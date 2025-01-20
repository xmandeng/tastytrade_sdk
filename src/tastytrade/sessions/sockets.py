import asyncio
import json
import logging
from asyncio import Semaphore
from collections import defaultdict
from typing import List

from injector import singleton
from websockets.asyncio.client import ClientConnection, connect

from tastytrade.sessions import Credentials
from tastytrade.sessions.configurations import CHANNEL_SPECS, DXLinkConfig
from tastytrade.sessions.enumerations import Channels
from tastytrade.sessions.models import (
    AddItem,
    AuthModel,
    FeedSetupModel,
    KeepaliveModel,
    OpenChannelModel,
    SessionReceivedModel,
    SetupModel,
    SubscriptionRequest,
)
from tastytrade.sessions.requests import AsyncSessionHandler

logger = logging.getLogger(__name__)


@singleton
class WebSocketManager:
    instance = None
    listener_task: asyncio.Task
    websocket: ClientConnection
    sessions: dict[AsyncSessionHandler, "WebSocketManager"] = {}
    queues: defaultdict[int, asyncio.Queue] = defaultdict(asyncio.Queue)
    lock = asyncio.Lock()
    session: AsyncSessionHandler

    def __new__(cls):
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(
        self,
    ):
        config = DXLinkConfig()
        self.subscription_semaphore = Semaphore(config.max_subscriptions)

    async def __aenter__(self, credentials: Credentials):
        await self.connect(credentials)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def connect(self, credentials: Credentials):
        self.session = await AsyncSessionHandler.create(credentials)
        self.websocket = await connect(self.session.session.headers["dxlink-url"])

        try:
            await self.setup_connection()
            await self.authorize_connection()
            await self.open_channels()
            await self.setup_feeds()
            await self.start_listener()

        except Exception as e:
            logger.error("Error while opening connection: %s", e)
            await self.websocket.close()
            raise e

    async def start_listener(self):
        self.listener_task = asyncio.create_task(self.socket_listener(), name="websocket_listener")

        self.keepalive_task = asyncio.create_task(
            self.send_keepalives(), name="websocket_keepalive"
        )

    async def close(self):
        if self.session in self.sessions:
            del self.sessions[self.session]

        if not hasattr(self, "websocket"):
            logger.warning("Websocket - No active connection to close")
            return

        tasks_to_cancel = [
            ("listener", getattr(self, "listener_task", None)),
            ("keepalive", getattr(self, "keepalive_task", None)),
        ]

        await asyncio.gather(
            *[self.cancel_task(name, task) for name, task in tasks_to_cancel if task is not None]
        )

        await self.websocket.close()
        logger.info("Websocket closed")
        self.websocket = None

    async def cancel_task(self, name: str, task: asyncio.Task):
        try:
            task.cancel()
            await task
            logger.info(f"{name} task cancelled")
        except asyncio.CancelledError:
            logger.info(f"{name} task was cancelled")

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

    async def send_keepalives(self):
        while True:
            try:
                await asyncio.sleep(30)
                await self.websocket.send(KeepaliveModel().model_dump_json())
                logger.debug("Keepalive sent from client")
            except asyncio.CancelledError:
                logger.info("Keepalive stopped")
                break
            except Exception as e:
                logger.error("Error sending keepalive: %s", e)
                break

    async def socket_listener(self):
        # TODO Consider using this websockets pattern which employs
        # TODOan async for loop: https://websockets.readthedocs.io/en/stable/howto/patterns.html
        while True:
            try:
                message = SessionReceivedModel(**json.loads(await self.websocket.recv()))
                channel = message.channel if message.type == "FEED_DATA" else 0

                try:
                    await asyncio.wait_for(self.queues[channel].put(message.fields), timeout=1)
                except asyncio.TimeoutError:
                    logger.warning(f"Queue {channel} is full - dropping message")

            except asyncio.CancelledError:
                logger.info("Websocket listener stopped")
                break
            except Exception as e:
                logger.error("Websocket listener error: %s", e)
                break
