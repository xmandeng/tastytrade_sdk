import asyncio
import json
import logging
from typing import Any, Optional

from injector import singleton
from websockets.asyncio.client import ClientConnection, connect

from tastytrade.sessions import Credentials
from tastytrade.sessions.messaging import MessageQueues
from tastytrade.sessions.models import (
    AuthModel,
    KeepaliveModel,
    OpenChannelModel,
    SessionReceivedModel,
    SetupModel,
)
from tastytrade.sessions.requests import AsyncSessionHandler

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)


@singleton
class WebSocketManager:
    listener_task: asyncio.Task
    websocket: ClientConnection
    sessions: dict[AsyncSessionHandler, "WebSocketManager"] = {}
    lock = asyncio.Lock()

    def __new__(cls, session):
        if session not in cls.sessions:
            cls.sessions[session] = super(WebSocketManager, cls).__new__(cls)
        return cls.sessions[session]

    def __init__(self, session: AsyncSessionHandler, queue_manager: Optional[MessageQueues] = None):
        self.session = session
        self.queue_manager = queue_manager or MessageQueues()

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def open(self):
        self.websocket = await connect(self.session.session.headers["dxlink-url"])

        try:
            # Setup sequence must happen before starting the listener
            await self.setup_connection()
            await self.authorize_connection()
            await self.open_channels()

            # Create websocket I/O tasks
            self.listener_task = asyncio.create_task(
                self.socket_listener(), name="websocket_listener"
            )
            self.keepalive_task = asyncio.create_task(
                self.send_keepalives(), name="websocket_keepalive"
            )

        except Exception as e:
            logger.error("Error while opening connection: %s", e)
            await self.websocket.close()
            self.websocket = None
            raise e

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
        for channel in self.queue_manager.queues:
            if channel == 0:
                continue

            request = OpenChannelModel(channel=channel)
            await asyncio.wait_for(self.websocket.send(request.model_dump_json()), timeout=5)

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
        # TODO Consider using this websockets pattern which employs and async for loop: https://websockets.readthedocs.io/en/stable/howto/patterns.html
        while True:
            try:
                message = SessionReceivedModel(**json.loads(await self.websocket.recv()))
                channel = message.channel if message.type == "FEED_DATA" else 0

                try:
                    await asyncio.wait_for(
                        self.queue_manager.queues[channel].put(message.fields), timeout=1
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Queue {channel} is full - dropping message")

            except asyncio.CancelledError:
                logger.info("Websocket listener stopped")
                break
            except Exception as e:
                logger.error("Websocket listener error: %s", e)
                break


async def main():
    # TODO Get rid of this
    try:
        session = await AsyncSessionHandler.create(Credentials(env="Test"))
    finally:
        await session.close()
