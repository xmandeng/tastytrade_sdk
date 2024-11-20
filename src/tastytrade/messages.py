import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


@dataclass
class Message:
    type: str
    channel: int
    data: Dict[str, Any]


class BaseMessageHandler(ABC):
    async def process_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.debug(f"Processing message type: {message.type}")
        await self.handle_message(message, websocket)

    @abstractmethod
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        pass


class SetupHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s", message.type)


class AuthStateHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s:%s", message.type, message.data.get("state"))


class ChannelOpenedHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s:CHANNEL.%s", message.data.get("type"), message.data.get("channel"))


class FeedConfigHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info(
            "%s:CHANNEL.%s:%s",
            message.data.get("type"),
            message.data.get("channel"),
            message.data.get("dataFormat"),
        )


class FeedDataHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.debug("Feed data received: %s", json.dumps(message.data, indent=2))
        # TODO Add feed data processing logic


class KeepaliveHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s:RECEIVED", message.type)
        await websocket.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))


class ErrorHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.error("%s:%s", message.data.get("error"), message.data.get("message"))


class MessageHandler:
    """Routes messages to appropriate handlers."""

    def __init__(self) -> None:
        self.handlers: Dict[str, BaseMessageHandler] = {
            "SETUP": SetupHandler(),
            "AUTH_STATE": AuthStateHandler(),
            "FEED_CONFIG": FeedConfigHandler(),
            "FEED_DATA": FeedDataHandler(),
            "KEEPALIVE": KeepaliveHandler(),
            "CHANNEL_OPENED": ChannelOpenedHandler(),
            "ERROR": ErrorHandler(),
        }

    async def route_message(self, raw_message: Dict[str, Any], websocket: ClientConnection) -> None:
        message = Message(
            type=raw_message.get("type", "UNKNOWN"),
            channel=raw_message.get("channel", 0),
            data=raw_message,
        )

        handler = self.handlers.get(message.type)
        if handler:
            await handler.process_message(message, websocket)
        else:
            logger.warning(f"No handler found for message type: {message.type}")
