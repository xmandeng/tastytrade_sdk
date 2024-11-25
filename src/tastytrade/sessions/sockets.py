import asyncio
import json
import logging
from typing import Any, Optional

from injector import singleton
from websockets.asyncio.client import ClientConnection, connect

from tastytrade.sessions import Credentials
from tastytrade.sessions.messages import MessageHandler, MessageQueue
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

    def __init__(
        self,
        session: AsyncSessionHandler,
        message_handler: MessageHandler = MessageHandler(),
        # TODO Event handler
    ):
        self.session = session
        self.url = session.session.headers["dxlink-url"]
        self.token = session.session.headers["token"]
        self.message_handler = message_handler
        self.message_queue = MessageQueue()
        self.channels: dict[int, str] = {}
        self.processor_task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def open(self):
        self.websocket = await connect(self.url)
        self.listener_task = asyncio.create_task(self.websocket_listener())
        self.processor_task = asyncio.create_task(self.process_message_queue())

        try:
            await self.setup_connection()
            await self.authorize_connection()

        except Exception as e:
            logger.error("Error during setup or authorization: %s", e)
            await self.websocket.close()
            self.websocket = None
            raise e

    async def close(self):
        if self.session in self.sessions:
            del self.sessions[self.session]

        if hasattr(self, "websocket"):
            await asyncio.sleep(0.25)

            # Cancel listener to stop receiving new messages
            if self.listener_task:
                try:
                    self.listener_task.cancel()
                    await self.listener_task
                    logger.info("Listener task cancelled")
                except asyncio.CancelledError:
                    logger.info("Listener task was cancelled")

            # Wait to process remaining enqueued messages
            try:
                await asyncio.wait_for(self.message_queue.join(), timeout=5.0)
                logger.info("All queued messages processed")
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for message queue to empty")

            # Cancel Queue processor task
            if self.processor_task:
                try:
                    self.processor_task.cancel()
                    await self.processor_task
                    logger.info("Processor task cancelled")
                except asyncio.CancelledError:
                    logger.info("Processor task was cancelled")

            await self.websocket.close()
            self.websocket = None
            logger.info("Websocket closed")
        else:
            logger.warning("Websocket - No active connection to close")

    async def setup_connection(self):
        setup = json.dumps(
            {
                "type": "SETUP",
                "channel": 0,
                "version": "0.1-DXF-JS/0.3.0",
                "keepaliveTimeout": 60,
                "acceptKeepaliveTimeout": 60,
            }
        )
        await asyncio.wait_for(self.websocket.send(setup), timeout=5)

    async def authorize_connection(self):
        authorize = json.dumps({"type": "AUTH", "channel": 0, "token": self.token})
        await asyncio.wait_for(self.websocket.send(authorize), timeout=5)

    async def websocket_listener(self):
        while True:
            try:
                message = await self.websocket.recv()
                parsed_message = json.loads(message)
                await self.message_queue.put(parsed_message)
            except asyncio.CancelledError:
                logger.info("Websocket listener stopped")
                break
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON received: %s", e)
            except Exception as e:
                logger.error("Websocket listener error: %s", e)
                break

    async def send_keepalive(self):
        pass

    async def process_message_queue(self):
        while True:
            try:
                message = await self.message_queue.get()
                await self.process_message(message)
            except asyncio.CancelledError:
                logger.info("Queue processor stopped")
                break
            except Exception as e:
                logger.error("Unexpected error in queue processor: %s", e)

    async def process_message(self, message):
        try:
            await self.message_handler.route_message(message, self.websocket)
        except Exception as e:
            logger.error("Error processing message: %s", e)
        finally:
            self.message_queue.task_done()


async def main():
    # TODO Get rid of this
    try:
        session = await AsyncSessionHandler.create(Credentials(env="Test"))
    finally:
        await session.close()
