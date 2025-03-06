import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

import redis.asyncio as redis  # type: ignore

import tastytrade.messaging.models.events as events
from tastytrade.config import ConfigurationManager
from tastytrade.messaging.models.events import BaseEvent

logger = logging.getLogger(__name__)


def event_model(message: dict[str, Any]) -> BaseEvent:
    channel = message["channel"].decode()
    data = json.loads(message["data"])
    event_type = channel.split(":")[1]
    if not event_type:

        logger.error("event_type is required: %s", message["channel"])
    return vars(events)[event_type](**data)


class DataSubscription(ABC):
    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def subscribe(
        self,
        channel_pattern: str,
        on_update: Callable,
    ) -> None:
        pass

    @abstractmethod
    async def unsubscribe(self, channel_pattern: str) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class RedisSubscription(DataSubscription):

    redis_url: str
    pubsub: redis.client.PubSub
    subscriptions: set[str]
    listener_task: asyncio.Task | None

    def __init__(self, config: ConfigurationManager):
        """Initialize Redis subscriber.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
        """
        self.redis_url: str = (
            f"redis://{config.get('host', 'redis')}:{config.get('port', 6379)}/{config.get('db', 0)}"
        )
        self.subscriptions = set()
        self.listener_task = None

    async def connect(self) -> None:
        """Establish connection to Redis."""
        self.client = redis.from_url(self.redis_url)
        self.pubsub = self.client.pubsub()
        logger.info("Listening to Redis at %s", self.redis_url)

    async def subscribe(
        self,
        channel_pattern: str,
        on_update: Callable = lambda x: None,
    ) -> None:
        """Subscribe to a channel or pattern and process messages.

        Args:
            channel_pattern: Channel pattern to subscribe to (e.g., "market:*" or "market:QuoteEvent:SPY")
        """
        logger.info("Subscribed to %s", channel_pattern)

        if channel_pattern not in self.subscriptions:
            await self.pubsub.psubscribe(channel_pattern)
            self.subscriptions.add(channel_pattern)

        if not self.listener_task:
            self.listener_task = asyncio.create_task(self.listener(on_update=on_update))
            self.listener_task.add_done_callback(handle_task_exception)

    async def listener(self, on_update: Callable) -> None:
        """Listen for messages across subscribed channels."""
        try:
            async for message in self.pubsub.listen():
                if (
                    message["type"] != "pmessage"
                    or message["pattern"].decode() not in self.subscriptions
                ):
                    continue

                try:
                    event = event_model(message)
                    logger.debug(f"Received message: {event}")

                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in message: {message['data']}")

                except Exception as e:
                    logger.error(f"Error processing message: {e}")

                on_update(event)

        except asyncio.CancelledError:
            logger.error("Redis pub/sub subscriptions cancelled")
        except Exception as e:
            logger.error("Subscription error: %s", e)

    async def unsubscribe(self, channel_pattern: str) -> None:
        """Unsubscribe from a channel pattern."""
        if self.pubsub is None:
            return

        await self.pubsub.punsubscribe(channel_pattern)

        # Cancel listener task
        if channel_pattern in self.subscriptions:
            self.subscriptions.discard(channel_pattern)

        logger.info("Unsubscribed from %s", channel_pattern)

    async def close(self) -> None:
        """Close all subscriptions and connection."""
        self.subscriptions.clear()

        if self.listener_task:
            self.listener_task.cancel()
            self.listener_task = None

        if self.pubsub:
            await self.pubsub.aclose()

        if hasattr(self, "client"):
            await self.client.aclose()

        logger.info("Redis connection closed")


def handle_task_exception(task: asyncio.Task):
    if task.exception():
        logger.error(f"Task failed with exception: {task.exception()}")
