import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


@dataclass
class Message:
    type: str
    channel: int
    data: Dict[str, Any]


class MessageProcessor(Protocol):
    """Protocol defining interface for message processors."""

    async def process(self, message: Message, websocket: ClientConnection) -> None: ...


class BaseMessageHandler:
    """Base handler with common functionality."""

    async def process_message(self, message: Message, websocket: ClientConnection) -> None:
        """Template method for processing messages."""
        logger.debug(f"Processing message type: {message.type}")
        await self._handle_message(message, websocket)

    async def _handle_message(self, message: Message, websocket: ClientConnection) -> None:
        raise NotImplementedError


class SetupMessageHandler(BaseMessageHandler):
    async def _handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("Setup message received: %s", message.type)
        # Add any specific setup handling logic here


class AuthStateMessageHandler(BaseMessageHandler):
    async def _handle_message(self, message: Message, websocket: ClientConnection) -> None:
        auth_state = message.data.get("state")
        logger.info("Auth state received: %s", auth_state)
        # Add authentication state specific logic here


class FeedDataMessageHandler(BaseMessageHandler):
    async def _handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.debug("Feed data received: %s", json.dumps(message.data, indent=2))
        # Add your feed data processing logic here


class KeepAliveMessageHandler(BaseMessageHandler):
    async def _handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("Keepalive message received")
        await websocket.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))


class ErrorMessageHandler(BaseMessageHandler):
    async def _handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.error("%s: %s", message.data.get("error"), message.data.get("message"))
        # Add error handling logic here


class MessageHandlerFactory:
    """Factory for creating message handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, BaseMessageHandler] = {
            "SETUP": SetupMessageHandler(),
            "AUTH_STATE": AuthStateMessageHandler(),
            "FEED_DATA": FeedDataMessageHandler(),
            "KEEPALIVE": KeepAliveMessageHandler(),
            "ERROR": ErrorMessageHandler(),
        }

    def get_handler(self, message_type: str) -> Optional[BaseMessageHandler]:
        return self._handlers.get(message_type)


class MessageRouter:
    """Routes messages to appropriate handlers."""

    def __init__(self):
        self.handler_factory = MessageHandlerFactory()

    async def route_message(self, raw_message: Dict[str, Any], websocket: ClientConnection) -> None:
        message = Message(
            type=raw_message.get("type", "UNKNOWN"),
            channel=raw_message.get("channel", 0),
            data=raw_message,
        )

        handler = self.handler_factory.get_handler(message.type)
        if handler:
            await handler.process_message(message, websocket)
        else:
            logger.warning(f"No handler found for message type: {message.type}")
