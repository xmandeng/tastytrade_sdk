import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TypeVar, cast

import redis  # type: ignore
import redis.asyncio  # type: ignore
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ConfigurationManager(ABC):
    """Abstract base class defining the configuration manager interface."""

    @abstractmethod
    def get(self, key: str, default: Any = None, value_type: Optional[Type[T]] = None) -> Any:
        """Get a configuration value."""
        pass

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value."""
        pass

    @abstractmethod
    def get_all(self) -> Dict[str, str]:
        """Get all configuration values."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a configuration value."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close any connections."""
        pass

    @abstractmethod
    def initialize(self, force: bool = False) -> None:
        """Initialize the configuration storage."""
        pass


class AsyncConfigurationManager(ABC):
    """Abstract base class defining the async configuration manager interface."""

    @abstractmethod
    async def get(self, key: str, default: Any = None, value_type: Optional[Type[T]] = None) -> Any:
        """Get a configuration value asynchronously."""
        pass

    @abstractmethod
    async def set(self, key: str, value: Any) -> None:
        """Set a configuration value asynchronously."""
        pass

    @abstractmethod
    async def get_all(self) -> Dict[str, str]:
        """Get all configuration values asynchronously."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a configuration value asynchronously."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any connections asynchronously."""
        pass

    @abstractmethod
    async def initialize(self, force: bool = False) -> None:
        """Initialize the configuration storage asynchronously."""
        pass


class ConfigManagerBase:
    """Base implementation with shared functionality for both sync and async managers."""

    def convert_value(self, value: str, value_type: Type[T]) -> T:
        """Convert a string value to the specified type."""
        if value_type is bool:
            return cast(T, value.lower() in ["true", "1", "yes", "y", "t"])
        elif value_type is int:
            return cast(T, int(value))
        elif value_type is float:
            return cast(T, float(value))
        elif value_type is list or value_type is List:
            try:
                return cast(T, json.loads(value))
            except json.JSONDecodeError:
                # Fall back to comma-separated values
                return cast(T, [item.strip() for item in value.split(",")])
        elif value_type is dict or value_type is Dict:
            return cast(T, json.loads(value))
        else:
            return cast(T, value)


class RedisConfigManager(ConfigManagerBase, ConfigurationManager):
    """Redis-backed synchronous configuration manager."""

    # ! CHANGE THIS FROM A SINGLETON TO UNQIUE PER NAMESPACE
    # Singleton instance
    instance = None

    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super(RedisConfigManager, cls).__new__(cls)
        return cls.instance

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
        redis_db: Optional[int] = None,
        namespace: str = "environment",
        env_file: Optional[str] = None,
    ):
        """Initialize the configuration manager.

        Args:
            redis_host: Redis host (defaults to env var REDIS_HOST or 'redis')
            redis_port: Redis port (defaults to env var REDIS_PORT or 6379)
            redis_db: Redis DB (defaults to env var REDIS_DB or 0)
            namespace: Namespace prefix for all configuration keys
            env_file: Path to .env file for loading variables (optional)
        """
        # Skip initialization if already initialized
        # if hasattr(self, "initialized"):
        #     return

        # Load environment variables from .env file
        self.env_file = env_file or ".env"
        env_vars = dotenv_values(self.env_file)

        self.namespace = namespace
        self.redis_client = redis.Redis(
            host=redis_host or env_vars.get("REDIS_HOST", "redis"),
            port=int(redis_port or env_vars.get("REDIS_PORT", 6379)),
            db=int(redis_db or env_vars.get("REDIS_DB", 0)),
        )
        self.initialized = False

    def get_hash_key(self) -> str:
        """Get the Redis hash key for environment variables."""
        return f"{self.namespace}"

    def initialize(self, force: bool = False) -> None:
        """Initialize configuration from .env file.

        This loads environment variables from .env into Redis.

        Args:
            force: Force reinitialization even if values already exist
        """
        if self.initialized and not force:
            return

        try:
            if env_vars := dotenv_values(self.env_file):
                hash_key = self.get_hash_key()
                self.redis_client.hset(hash_key, mapping=env_vars)
                logger.info(f"Initialized {len(env_vars)} variables from .env file in Redis")
            else:
                logger.warning(f"No variables found in .env file: {self.env_file}")

            self.initialized = True

        except FileNotFoundError:
            logger.warning(f".env file not found: {self.env_file}")
            self.initialized = True  # Still mark as initialized to avoid repeated attempts
        except Exception as e:
            logger.error(f"Error initializing configuration: {e}")
            raise

    def get(self, key: str, default: Any = None, value_type: Optional[Type[T]] = None) -> Any:
        """Get a configuration value.

        Args:
            key: Configuration key
            default: Default value if key doesn't exist
            value_type: Type to convert the value to

        Returns:
            The configuration value
        """
        logger.debug(f"Getting {key} from Redis")
        hash_key = self.get_hash_key()
        value = self.redis_client.hget(hash_key, key)

        # Return default if not found
        if value is None:
            return default

        # Decode bytes to string
        value = value.decode("utf-8")

        # Convert value type if specified
        if value_type is not None:
            value = self.convert_value(value, value_type)

        return value

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        # Convert non-string values
        if not isinstance(value, str):
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            else:
                value = str(value)

        # Store in Redis
        hash_key = self.get_hash_key()
        self.redis_client.hset(hash_key, key, value)

    def get_all(self) -> Dict[str, str]:
        """Get all configuration values.

        Returns:
            Dictionary of configuration values
        """
        logger.debug("Getting all configuration values from Redis")
        hash_key = self.get_hash_key()
        values = self.redis_client.hgetall(hash_key)

        # Convert bytes to strings
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in values.items()}

    def delete(self, key: str) -> None:
        """Delete a configuration value.

        Args:
            key: Configuration key
        """
        hash_key = self.get_hash_key()
        self.redis_client.hdel(hash_key, key)

    def close(self) -> None:
        """Close the Redis connection."""
        self.redis_client.close()


class AsyncRedisConfigManager(ConfigManagerBase, AsyncConfigurationManager):
    """Redis-backed asynchronous configuration manager."""

    # ! CHANGE THIS FROM A SINGLETON TO UNQIUE PER NAMESPACE
    # Singleton instance
    instance = None

    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super(AsyncRedisConfigManager, cls).__new__(cls)
        return cls.instance

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
        redis_db: Optional[int] = None,
        namespace: str = "environment",
        env_file: Optional[str] = None,
    ):
        """Initialize the configuration manager.

        Args:
            redis_host: Redis host (defaults to env var REDIS_HOST or 'redis')
            redis_port: Redis port (defaults to env var REDIS_PORT or 6379)
            redis_db: Redis DB (defaults to env var REDIS_DB or 0)
            namespace: Namespace prefix for all configuration keys
            env_file: Path to .env file for loading variables (optional)
        """
        # Skip initialization if already initialized
        if hasattr(self, "initialized"):
            return

        # Load environment variables from .env file
        self.env_file = env_file or ".env"
        env_vars = dotenv_values(self.env_file)

        self.namespace = namespace
        self.redis_client = redis.asyncio.Redis(
            host=redis_host or env_vars.get("REDIS_HOST", "redis"),
            port=int(redis_port or env_vars.get("REDIS_PORT", 6379)),
            db=int(redis_db or env_vars.get("REDIS_DB", 0)),
        )
        self.initialized = False

    def get_hash_key(self) -> str:
        """Get the Redis hash key for environment variables."""
        return f"{self.namespace}"

    async def initialize(self, force: bool = False) -> None:
        """Initialize configuration from .env file.

        This loads environment variables from .env into Redis.

        Args:
            force: Force reinitialization even if values already exist
        """
        if self.initialized and not force:
            return

        try:
            if env_vars := dotenv_values(self.env_file):
                hash_key = self.get_hash_key()
                await self.redis_client.hset(hash_key, mapping=env_vars)
                logger.info(f"Initialized {len(env_vars)} variables from .env file in Redis")
            else:
                logger.warning(f"No variables found in .env file: {self.env_file}")

            self.initialized = True

        except FileNotFoundError:
            logger.warning(f".env file not found: {self.env_file}")
            self.initialized = True  # Still mark as initialized to avoid repeated attempts
        except Exception as e:
            logger.error(f"Error initializing configuration: {e}")
            raise

    async def get(self, key: str, default: Any = None, value_type: Optional[Type[T]] = None) -> Any:
        """Get a configuration value asynchronously.

        Args:
            key: Configuration key
            default: Default value if key doesn't exist
            value_type: Type to convert the value to

        Returns:
            The configuration value
        """
        logger.debug(f"Getting {key} from Redis")
        hash_key = self.get_hash_key()
        value = await self.redis_client.hget(hash_key, key)

        # Return default if not found
        if value is None:
            return default

        # Decode bytes to string
        value = value.decode("utf-8")

        # Convert value type if specified
        if value_type is not None:
            value = self.convert_value(value, value_type)

        return value

    async def set(self, key: str, value: Any) -> None:
        """Set a configuration value asynchronously.

        Args:
            key: Configuration key
            value: Configuration value
        """
        # Convert non-string values
        if not isinstance(value, str):
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            else:
                value = str(value)

        # Store in Redis
        hash_key = self.get_hash_key()
        await self.redis_client.hset(hash_key, key, value)

    async def get_all(self) -> Dict[str, str]:
        """Get all configuration values asynchronously.

        Returns:
            Dictionary of configuration values
        """
        logger.debug("Getting all configuration values from Redis")
        hash_key = self.get_hash_key()
        values = await self.redis_client.hgetall(hash_key)

        # Convert bytes to strings
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in values.items()}

    async def delete(self, key: str) -> None:
        """Delete a configuration value asynchronously.

        Args:
            key: Configuration key
        """
        hash_key = self.get_hash_key()
        await self.redis_client.hdel(hash_key, key)

    async def close(self) -> None:
        """Close the Redis connection asynchronously."""
        await self.redis_client.close()
