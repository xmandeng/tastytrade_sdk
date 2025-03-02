import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

# Add type ignore comment for redis imports
import redis.asyncio as redis  # type: ignore

logger = logging.getLogger(__name__)


class SubscriptionStore(ABC):
    @abstractmethod
    async def add_subscription(
        self, symbol: str, metadata: Optional[dict[Any, Any]] = None
    ) -> None:
        """Add a subscription to the store"""
        pass

    @abstractmethod
    async def remove_subscription(self, symbol: str) -> None:
        """Remove a subscription from the store"""
        pass

    @abstractmethod
    async def get_active_subscriptions(self) -> dict:
        """Get all active subscriptions"""
        pass

    @abstractmethod
    async def update_subscription_status(self, symbol: str, data: dict) -> None:
        """Update subscription status"""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the subscription store"""
        pass


class RedisSubscriptionStore(SubscriptionStore):
    """Redis-backed implementation of SubscriptionStore using a hash structure."""

    def __init__(
        self,
        hash_key: str = "subscriptions",
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: Optional[int] = 0,
    ):
        self.hash_key = hash_key
        self.redis = redis.Redis(
            host=host or os.environ.get("REDIS_HOST", "redis"),
            port=port or os.environ.get("REDIS_PORT", 6379),
            db=db or os.environ.get("REDIS_DB", 0),
        )

    async def add_subscription(
        self, symbol: str, metadata: Optional[dict[Any, Any]] = None
    ) -> None:
        data = {
            "active": True,
            "last_update": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        # Use HSET instead of SET
        await self.redis.hset(self.hash_key, symbol, json.dumps(data))

    async def remove_subscription(self, symbol: str) -> None:
        # Get the current data from the hash, update active status, and save back
        if data_str := await self.redis.hget(self.hash_key, symbol):
            data = json.loads(data_str.decode("utf-8"))
            data["active"] = False
            data["last_update"] = datetime.now(timezone.utc).isoformat()
            await self.redis.hset(self.hash_key, symbol, json.dumps(data))

    async def get_active_subscriptions(self) -> dict:
        # Get all subscriptions from the hash at once
        all_subscriptions = await self.redis.hgetall(self.hash_key)
        result = {}

        for key_bytes, data_bytes in all_subscriptions.items():
            key = key_bytes.decode("utf-8")
            data = json.loads(data_bytes.decode("utf-8"))
            if data.get("active", False):
                result[key] = data

        return result

    async def update_subscription_status(self, symbol: str, data: dict[str, Any]) -> None:
        """
        Updates the metadata and timestamp of a subscription in Redis.

        Args:
            symbol: The exact symbol identifier (e.g., "SPX{=d}")
            data: dictionary of metadata to merge with existing subscription metadata
        """
        # Try both formats (with/without interval)

        # For candle subscriptions, we need to find all keys with the symbol as prefix

        if data_bytes := await self.redis.hget(self.hash_key, symbol):
            subscription_data = json.loads(data_bytes.decode("utf-8"))
            subscription_data["last_update"] = datetime.now(timezone.utc).isoformat()
            subscription_data["metadata"].update(data)
            await self.redis.hset(self.hash_key, symbol, json.dumps(subscription_data))

    async def initialize(self) -> None:
        """Async initialization method to be called after creation.

        Establishes and verifies the Redis connection, logs connection status and Redis server information.
        This method must be called after instantiation since async operations cannot be performed in __init__.

        Raises:
            ConnectionError: If Redis connection fails or times out
        """
        try:
            response = await self.redis.ping()
            logger.info("Redis ping response: %s", response)

            # Get Redis info
            info = await self.redis.info()
            logger.info("Redis version: %s", info["redis_version"])
            logger.info("Connected clients: %s", info["connected_clients"])
        except Exception as e:
            logger.error("Error initializing Redis connection: %s", e)
            raise ConnectionError(f"Failed to establish Redis connection: {e}")


class InMemorySubscriptionStore(SubscriptionStore):
    instance = None
    initialized = False

    def __new__(cls):
        if cls.instance is None:
            cls.instance = super(InMemorySubscriptionStore, cls).__new__(cls)
        return cls.instance

    def __init__(self):
        if not self.initialized:
            self.subscriptions = {}
            self.initialized = True

    async def initialize(self) -> None:
        """Initialize the subscription store"""
        # This method is required by the abstract base class
        pass

    async def add_subscription(
        self, symbol: str, metadata: Optional[dict[Any, Any]] = None
    ) -> None:
        self.subscriptions[symbol] = {
            "subscribe_time": datetime.now(timezone.utc).isoformat(),
            "active": True,
            "metadata": metadata or {},
        }

    async def remove_subscription(self, symbol: str) -> None:
        if symbol in self.subscriptions:
            self.subscriptions[symbol]["active"] = False

    async def get_active_subscriptions(self) -> dict:
        return {symbol: data for symbol, data in self.subscriptions.items() if data["active"]}

    async def update_subscription_status(self, symbol: str, data: dict) -> None:
        # Try both formats (with/without interval)
        keys_to_try = [symbol]

        # Try to find keys that start with this symbol (for candle subscriptions)
        keys_to_try.extend([k for k in self.subscriptions.keys() if k.startswith(f"{symbol}_")])

        for key in keys_to_try:
            if key in self.subscriptions:
                self.subscriptions[key]["last_update"] = datetime.now(timezone.utc).isoformat()
                self.subscriptions[key]["metadata"].update(data)
