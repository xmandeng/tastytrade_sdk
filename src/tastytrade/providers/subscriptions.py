import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Callable

import redis as sync_redis
import redis.asyncio as redis  # type: ignore

import tastytrade.messaging.models.events as events
from tastytrade.config import ConfigurationManager
from tastytrade.messaging.models.events import BaseEvent

logger = logging.getLogger(__name__)


class DataSubscription(ABC):
    queue: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def subscribe(
        self,
        channel_pattern: str,
        event_type: type[BaseEvent] | None = None,
        on_update: Callable = lambda x: None,
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
            config: Configuration manager for Redis connection settings.
        """
        self.redis_url: str = (
            f"redis://{config.get('host', 'localhost')}"
            f":{config.get('port', 6379)}"
            f"/{config.get('db', 0)}"
        )
        self.subscriptions = set()
        self.listener_task = None
        self._event_types: dict[str, type[BaseEvent]] = {}

    async def connect(self) -> None:
        """Establish connection to Redis."""
        self.client = redis.from_url(self.redis_url)
        self.pubsub = self.client.pubsub()
        logger.info("Listening to Redis at %s", self.redis_url)

    async def subscribe(
        self,
        channel_pattern: str,
        event_type: type[BaseEvent] | None = None,
        on_update: Callable = lambda x: None,
    ) -> None:
        """Subscribe to a channel or pattern and process messages.

        Args:
            channel_pattern: Channel pattern to subscribe to
                (e.g., "market:CandleEvent:SPX{=5m}")
            event_type: The expected event type for this channel. When provided,
                messages are deserialized directly into this type and contract
                violations are logged as errors. When ``None``, the type is
                inferred from the channel name (backward-compatible fallback).
            on_update: Optional callback for incoming events.
        """
        if event_type is not None:
            logger.info(
                "Subscribed to %s (type=%s)",
                channel_pattern,
                event_type.__name__,
            )
            self._event_types[channel_pattern] = event_type
        else:
            logger.info("Subscribed to %s", channel_pattern)

        if channel_pattern not in self.subscriptions:
            await self.pubsub.psubscribe(channel_pattern)
            self.subscriptions.add(channel_pattern)

        if not self.listener_task:
            self.listener_task = asyncio.create_task(self.listener())
            self.listener_task.add_done_callback(handle_task_exception)

    async def listener(self) -> None:
        """Listen for messages across subscribed channels."""
        try:
            async for message in self.pubsub.listen():
                if (
                    message["type"] != "pmessage"
                    or message["pattern"].decode() not in self.subscriptions
                ):
                    continue

                channel = message["channel"].decode()
                pattern = message["pattern"].decode()

                try:
                    data = json.loads(message["data"])
                except json.JSONDecodeError:
                    logger.error("Invalid JSON on %s: %s", channel, message["data"])
                    continue

                # Typed deserialization when event_type was declared
                event_type = self._event_types.get(pattern)
                if event_type is not None:
                    try:
                        event: BaseEvent = event_type(**data)
                    except Exception as e:
                        logger.error(
                            "Contract violation on %s: expected %s, got: %s",
                            channel,
                            event_type.__name__,
                            e,
                        )
                        continue
                else:
                    # Fallback: infer type from channel name
                    type_name = channel.split(":")[1] if ":" in channel else ""
                    event_cls = getattr(events, type_name, None)
                    if event_cls is None:
                        logger.error(
                            "Unknown event type '%s' on channel: %s",
                            type_name,
                            channel,
                        )
                        continue
                    try:
                        event = event_cls(**data)
                    except Exception as e:
                        logger.error("Error deserializing %s: %s", channel, e)
                        continue

                self.queue[
                    f"{event.__class__.__name__}:{event.eventSymbol}"
                ].put_nowait(event)
                logger.debug(
                    "Received %s on %s",
                    event.__class__.__name__,
                    channel,
                )

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
            await self.pubsub.aclose()  # type: ignore[attr-defined]

        if hasattr(self, "client"):
            await self.client.aclose()  # type: ignore[attr-defined]

        logger.info("Redis connection closed")


class RedisPublisher:
    """Publishes BaseEvent instances to Redis pub/sub channels.

    Channel format: market:{class_name}:{eventSymbol}
    Same format as RedisEventProcessor, but decoupled from the
    BaseEventProcessor protocol.
    """

    def __init__(
        self,
        redis_host: str | None = None,
        redis_port: int | None = None,
    ) -> None:
        host = (
            redis_host
            if redis_host is not None
            else os.environ.get("REDIS_HOST", "localhost")
        )
        port = (
            redis_port
            if redis_port is not None
            else int(os.environ.get("REDIS_PORT", "6379"))
        )
        self.redis = sync_redis.Redis(host=host, port=port)

    def publish(self, event: BaseEvent) -> None:
        channel = f"market:{event.__class__.__name__}:{event.eventSymbol}"
        self.redis.publish(channel=channel, message=event.model_dump_json())

    def close(self) -> None:
        self.redis.close()


def handle_task_exception(task: asyncio.Task) -> None:
    if task.exception():
        logger.error("Task failed with exception: %s", task.exception())
