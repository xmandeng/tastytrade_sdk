import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from websockets.asyncio.client import ClientConnection

from .models import EventType
from .parsers import EventParser

logger = logging.getLogger(__name__)

# Type for callback functions
CallbackType = Callable[[EventType], Any]


@dataclass
class Message:
    type: str
    channel: int
    data: Dict[str, Any]


@dataclass
class EventCallback:
    callback: CallbackType
    symbols: Optional[List[str]] = None


class BaseMessageHandler(ABC):
    async def process_message(self, message: Message, websocket: ClientConnection) -> None:
        await self.handle_message(message, websocket)

    @abstractmethod
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        pass


class KeepaliveHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s:Received", message.type)
        await websocket.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))


class ErrorHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.error("%s:%s", message.data.get("error"), message.data.get("message"))


class SetupHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s", message.type)


class AuthStateHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s:%s", message.type, message.data.get("state"))


class ChannelOpenedHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info("%s:%s", message.data.get("type"), message.data.get("channel"))


class FeedConfigHandler(BaseMessageHandler):
    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        logger.info(
            "%s:%s:%s",
            message.data.get("type"),
            message.data.get("channel"),
            message.data.get("dataFormat"),
        )


class FeedDataHandler(BaseMessageHandler):
    def __init__(self) -> None:
        self.parser = EventParser()
        self.callbacks: Dict[str, List[EventCallback]] = {
            "Trade": [],
            "TradeETH": [],
            "Quote": [],
            "Greeks": [],
            "Profile": [],
            "Summary": [],
        }

    def add_callback(
        self, event_type: str, callback: CallbackType, symbols: Optional[List[str]] = None
    ) -> None:
        """Register a callback for specific event type and optionally specific symbols."""
        self.callbacks[event_type].append(EventCallback(callback, symbols))

    async def handle_message(self, message: Message, websocket: ClientConnection) -> None:
        try:
            event_type = message.data["data"][0]
            event = await self.parser.route_event(message.data["data"])

            if event:
                # Call registered callbacks for this event type
                for callback in self.callbacks[event_type]:
                    if callback.symbols is None or event.symbol in callback.symbols:
                        await callback.callback(event)

                logger.debug("Processed %s event for %s", event_type, event.symbol)
            else:
                logger.warning("Unknown event type: %s", event_type)

        except Exception as e:
            logger.error("Error processing feed data: %s", e)


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

        if handler := self.handlers.get(message.type):
            await handler.process_message(message, websocket)
        else:
            logger.warning(f"No handler found for message type: {message.type}")
