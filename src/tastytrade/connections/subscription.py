# 1. Create a subscription store interface
import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

# Add type ignore comment for redis imports
import redis.asyncio as redis  # type: ignore

logger = logging.getLogger(__name__)


class SubscriptionStore(ABC):
    @abstractmethod
    async def add_subscription(
        self, symbol: str, interval: Optional[str] = None, metadata: Optional[Dict[Any, Any]] = None
    ) -> None:
        """Add a subscription to the store"""
        pass

    @abstractmethod
    async def remove_subscription(self, symbol: str, interval: Optional[str] = None) -> None:
        """Remove a subscription from the store"""
        pass

    @abstractmethod
    async def get_active_subscriptions(self) -> Dict:
        """Get all active subscriptions"""
        pass

    @abstractmethod
    async def update_subscription_status(self, symbol: str, data: Dict) -> None:
        """Update subscription status"""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the subscription store"""
        pass


class RedisSubscriptionStore(SubscriptionStore):
    """Redis-backed implementation of SubscriptionStore."""

    def __init__(
        self, host: Optional[str] = None, port: Optional[int] = None, db: Optional[int] = 0
    ):
        redis_client = redis.Redis(
            host=host or os.environ.get("REDIS_HOST", "redis"),
            port=port or os.environ.get("REDIS_PORT", 6379),
            db=db or os.environ.get("REDIS_DB", 0),
        )

        self.subscription_prefix = "subscription:"

        self.redis = redis_client

    async def initialize(self):
        """Async initialization method to be called after creation.

        Establishes and verifies the Redis connection, logs connection status and Redis server information.
        This method must be called after instantiation since async operations cannot be performed in __init__.

        Returns:
            bool: True if connection was successful, False otherwise

        Raises:
            Exception: If Redis connection fails or times out
        """
        try:
            response = await asyncio.wait_for(self.redis.ping(), timeout=5)
            logger.info("Redis ping response: %s", response)

            # Get Redis info
            info = await self.redis.info()
            logger.info("Redis version: %s", info["redis_version"])
            logger.info("Connected clients: %s", info["connected_clients"])
        except Exception as e:
            logger.error("Error initializing Redis connection: %s", e)
            raise ConnectionError(f"Failed to establish Redis connection: {e}")

    async def add_subscription(
        self, symbol: str, interval: Optional[str] = None, metadata: Optional[Dict[Any, Any]] = None
    ) -> None:
        key = self.make_key(symbol, interval)
        data = {
            "symbol": symbol,
            "interval": interval,
            "subscribe_time": datetime.now().isoformat(),
            "active": True,
            "last_update": None,
            "metadata": metadata or {},
        }
        # Await the Redis set operation
        await self.redis.set(f"{self.subscription_prefix}{key}", json.dumps(data))

    async def remove_subscription(self, symbol: str, interval: Optional[str] = None) -> None:
        key = self.make_key(symbol, interval)
        # Get the current data, update active status, and save
        data_str = await self.redis.get(f"{self.subscription_prefix}{key}")
        if data_str:
            data = json.loads(data_str.decode("utf-8"))  # Decode bytes to string
            data["active"] = False
            await self.redis.set(f"{self.subscription_prefix}{key}", json.dumps(data))

    async def get_active_subscriptions(self) -> Dict:
        # Get all keys matching the pattern - await the keys operation
        keys = await self.redis.keys(f"{self.subscription_prefix}*")
        result = {}

        for key in keys:
            # Await the get operation
            data_bytes = await self.redis.get(key)
            if data_bytes:
                data = json.loads(data_bytes.decode("utf-8"))  # Decode bytes to string
                if data.get("active", False):
                    # Remove the prefix from the key
                    clean_key = key.decode("utf-8").replace(self.subscription_prefix, "")
                    result[clean_key] = data

        return result

    async def update_subscription_status(self, symbol: str, data: Dict) -> None:
        # Try both formats (with/without interval)
        keys_to_try = [symbol]

        # Try to find keys that start with this symbol (for candle subscriptions)
        pattern_keys = await self.redis.keys(f"{self.subscription_prefix}{symbol}_*")
        keys_to_try.extend(
            [k.decode("utf-8").replace(self.subscription_prefix, "") for k in pattern_keys]
        )

        for key in keys_to_try:
            data_bytes = await self.redis.get(f"{self.subscription_prefix}{key}")
            if data_bytes:
                subscription_data = json.loads(data_bytes.decode("utf-8"))
                subscription_data["last_update"] = datetime.now().isoformat()
                subscription_data["metadata"].update(data)
                await self.redis.set(
                    f"{self.subscription_prefix}{key}", json.dumps(subscription_data)
                )

    def make_key(self, symbol: str, interval: Optional[str] = None) -> str:
        return f"{symbol}{f'_{interval}' if interval else ''}"


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
        self, symbol: str, interval: Optional[str] = None, metadata: Optional[Dict[Any, Any]] = None
    ) -> None:
        key = self.make_key(symbol, interval)
        self.subscriptions[key] = {
            "symbol": symbol,
            "interval": interval,
            "subscribe_time": datetime.now(),
            "active": True,
            "metadata": metadata or {},
        }

    async def remove_subscription(self, symbol: str, interval: Optional[str] = None) -> None:
        key = self.make_key(symbol, interval)
        if key in self.subscriptions:
            self.subscriptions[key]["active"] = False

    async def get_active_subscriptions(self) -> Dict:
        return {k: v for k, v in self.subscriptions.items() if v["active"]}

    async def update_subscription_status(self, symbol: str, data: Dict) -> None:
        # Try both formats (with/without interval)
        keys_to_try = [symbol]

        # Try to find keys that start with this symbol (for candle subscriptions)
        keys_to_try.extend([k for k in self.subscriptions.keys() if k.startswith(f"{symbol}_")])

        for key in keys_to_try:
            if key in self.subscriptions:
                self.subscriptions[key]["last_update"] = datetime.now()
                self.subscriptions[key]["metadata"].update(data)

    def make_key(self, symbol: str, interval: Optional[str] = None) -> str:
        return f"{symbol}{f'_{interval}' if interval else ''}"
