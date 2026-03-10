"""Tests for the service discovery and configuration resolution scheme.

These tests enforce the layered resolution contract described in
docs/SERVICE_DISCOVERY.md. The resolution order is:

    os.environ  →  Redis (.env file)  →  Code default
       (1)              (2)                  (3)

The design ensures the application works in both the Docker devcontainer
(where services are reached via Docker DNS names like "redis") and on the
host machine (where services are reached via "localhost" through port mapping).

Key invariants guarded by these tests:

1. Code defaults MUST be host-friendly ("localhost"), not Docker DNS names.
   See: docs/SERVICE_DISCOVERY.md § "DO NOT change code defaults"

2. os.environ MUST take precedence over .env file values and code defaults.
   This is how Docker Compose `environment` overrides work inside the container.
   See: docs/SERVICE_DISCOVERY.md § "Layer 1: os.environ"

3. Service hostnames MUST NOT appear in .env — they belong in os.environ
   (set by Docker Compose) or code defaults.
   See: docs/SERVICE_DISCOVERY.md § "DO NOT put service hostnames in .env"

4. config.get() MUST check os.environ before Redis, so Docker Compose
   overrides take effect even for keys not present in .env.
   See: docs/SERVICE_DISCOVERY.md § "Layer 1: os.environ"
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from tastytrade.config.manager import RedisConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the RedisConfigManager singleton between tests.

    The singleton pattern caches the first instance. Without resetting,
    test isolation breaks because __init__ is skipped on subsequent calls.
    """
    RedisConfigManager.instance = None
    yield
    RedisConfigManager.instance = None


def _make_manager(
    env_overrides: dict[str, str] | None = None,
    dotenv_values: dict[str, str | None] | None = None,
) -> RedisConfigManager:
    """Create a RedisConfigManager with mocked Redis and dotenv.

    Args:
        env_overrides: Values to inject into os.environ for the test.
        dotenv_values: Values that dotenv_values() should return (simulates .env file).
    """
    dotenv_return = dotenv_values or {}
    env = env_overrides or {}

    with (
        patch("tastytrade.config.manager.redis.Redis"),
        patch(
            "tastytrade.config.manager.dotenv_values",
            return_value=dotenv_return,
        ),
        patch.dict(os.environ, env, clear=False),
    ):
        return RedisConfigManager(env_file="/dev/null")


# ---------------------------------------------------------------------------
# 1. Code defaults — MUST be host-friendly
#
# See docs/SERVICE_DISCOVERY.md § "DO NOT change code defaults"
# If these break, the host environment stops working.
# ---------------------------------------------------------------------------


class TestCodeDefaultsAreHostFriendly:
    """Code defaults must use localhost so the host environment works
    without any environment variables or .env configuration.

    Reference: docs/SERVICE_DISCOVERY.md § "Layer 3: Code defaults"
    """

    def test_redis_host_defaults_to_localhost(self) -> None:
        """With no env vars and no .env, Redis host must be localhost."""
        with (
            patch("tastytrade.config.manager.redis.Redis") as mock_redis,
            patch("tastytrade.config.manager.dotenv_values", return_value={}),
            patch.dict(os.environ, {}, clear=True),
        ):
            RedisConfigManager(env_file="/dev/null")
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "localhost"

    def test_redis_host_not_docker_dns_name(self) -> None:
        """Redis host must NOT default to 'redis' (Docker DNS name).

        Reverting to 'redis' would break the host environment because
        Docker DNS names don't resolve outside the container network.
        """
        with (
            patch("tastytrade.config.manager.redis.Redis") as mock_redis,
            patch("tastytrade.config.manager.dotenv_values", return_value={}),
            patch.dict(os.environ, {}, clear=True),
        ):
            RedisConfigManager(env_file="/dev/null")
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] != "redis", (
                "Default must be 'localhost', not 'redis'. "
                "See docs/SERVICE_DISCOVERY.md § 'DO NOT change code defaults'"
            )

    def test_influxdb_url_defaults_to_localhost(self) -> None:
        """config.get() for INFLUX_DB_URL must fall through to localhost default."""
        manager = _make_manager()
        # Mock Redis hget to return None (key not in Redis)
        manager.redis_client.hget = MagicMock(return_value=None)  # type: ignore[method-assign]

        url = manager.get("INFLUX_DB_URL", "http://localhost:8086")
        assert url == "http://localhost:8086"

    def test_influxdb_url_not_docker_dns_name(self) -> None:
        """INFLUX_DB_URL must NOT default to http://influxdb:8086.

        Reverting to the Docker DNS URL would break host-side usage.
        """
        manager = _make_manager()
        manager.redis_client.hget = MagicMock(return_value=None)  # type: ignore[method-assign]

        # The default passed by callers must use localhost
        url = manager.get("INFLUX_DB_URL", "http://localhost:8086")
        assert "influxdb" not in url, (
            "Default must use 'localhost', not 'influxdb'. "
            "See docs/SERVICE_DISCOVERY.md § 'DO NOT change code defaults'"
        )


# ---------------------------------------------------------------------------
# 2. os.environ precedence — MUST override .env and defaults
#
# See docs/SERVICE_DISCOVERY.md § "Layer 1: os.environ"
# This is how Docker Compose `environment` overrides work.
# ---------------------------------------------------------------------------


class TestOsEnvironTakesPrecedence:
    """os.environ must be the highest-priority config source.

    Inside the devcontainer, Docker Compose sets os.environ via the
    `environment` section. These values must override both .env file
    values (loaded into Redis) and code defaults.

    Reference: docs/SERVICE_DISCOVERY.md § "Layer 1: os.environ"
    """

    def test_get_returns_os_environ_over_redis(self) -> None:
        """config.get() must return os.environ value even when Redis has a
        different value for the same key."""
        manager = _make_manager()
        manager.redis_client.hget = MagicMock(return_value=b"from_redis")  # type: ignore[method-assign]

        with patch.dict(os.environ, {"MY_KEY": "from_environ"}, clear=False):
            assert manager.get("MY_KEY") == "from_environ"

    def test_get_returns_os_environ_over_default(self) -> None:
        """config.get() must return os.environ value over the caller's default."""
        manager = _make_manager()

        with patch.dict(
            os.environ, {"INFLUX_DB_URL": "http://influxdb:8086"}, clear=False
        ):
            result = manager.get("INFLUX_DB_URL", "http://localhost:8086")
            assert result == "http://influxdb:8086"

    def test_get_skips_redis_when_environ_present(self) -> None:
        """When os.environ has the key, Redis should not be queried at all.

        This avoids unnecessary Redis round-trips for values that are
        already known from the runtime environment.
        """
        manager = _make_manager()
        manager.redis_client.hget = MagicMock()  # type: ignore[method-assign]

        with patch.dict(os.environ, {"SOME_KEY": "env_value"}, clear=False):
            manager.get("SOME_KEY")
            manager.redis_client.hget.assert_not_called()

    def test_get_with_value_type_converts_environ_value(self) -> None:
        """os.environ values must be type-converted when value_type is specified."""
        manager = _make_manager()

        with patch.dict(os.environ, {"REDIS_PORT": "6380"}, clear=False):
            result = manager.get("REDIS_PORT", value_type=int)
            assert result == 6380
            assert isinstance(result, int)

    def test_bootstrap_prefers_os_environ_over_dotenv(self) -> None:
        """Redis client bootstrap must use os.environ over .env file values.

        This is critical for the devcontainer: Docker Compose sets
        REDIS_HOST=redis in os.environ, which must override any value
        from the .env file.
        """
        with (
            patch("tastytrade.config.manager.redis.Redis") as mock_redis,
            patch(
                "tastytrade.config.manager.dotenv_values",
                return_value={"REDIS_HOST": "from-dotenv"},
            ),
            patch.dict(os.environ, {"REDIS_HOST": "from-environ"}, clear=False),
        ):
            RedisConfigManager(env_file="/dev/null")
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "from-environ"


# ---------------------------------------------------------------------------
# 3. .env file fallback — Layer 2 when os.environ is absent
#
# See docs/SERVICE_DISCOVERY.md § "Layer 2: Redis"
# ---------------------------------------------------------------------------


class TestDotenvFallback:
    """When os.environ does not have a key, the .env file value (via
    dotenv_values) should be used for Redis bootstrap.

    Reference: docs/SERVICE_DISCOVERY.md § "Layer 2: Redis"
    """

    def test_bootstrap_uses_dotenv_when_no_environ(self) -> None:
        """If os.environ has no REDIS_HOST, bootstrap should use .env value."""
        env_clean = {k: v for k, v in os.environ.items() if k != "REDIS_HOST"}
        with (
            patch("tastytrade.config.manager.redis.Redis") as mock_redis,
            patch(
                "tastytrade.config.manager.dotenv_values",
                return_value={"REDIS_HOST": "redis-from-dotenv"},
            ),
            patch.dict(os.environ, env_clean, clear=True),
        ):
            RedisConfigManager(env_file="/dev/null")
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "redis-from-dotenv"

    def test_get_falls_through_to_redis_when_no_environ(self) -> None:
        """config.get() should query Redis when os.environ has no value."""
        env_clean = {k: v for k, v in os.environ.items() if k != "MY_KEY"}
        with patch.dict(os.environ, env_clean, clear=True):
            manager = _make_manager()
            manager.redis_client.hget = MagicMock(return_value=b"redis_value")  # type: ignore[method-assign]

            result = manager.get("MY_KEY")
            assert result == "redis_value"
            manager.redis_client.hget.assert_called_once()


# ---------------------------------------------------------------------------
# 4. initialize() — must merge os.environ on top of .env values
#
# See docs/SERVICE_DISCOVERY.md § "Layer 1: os.environ"
# ---------------------------------------------------------------------------


class TestInitializeOsEnvironOverride:
    """initialize() loads .env into Redis, but must apply os.environ
    overrides so that Docker Compose values persist into Redis.

    Reference: docs/SERVICE_DISCOVERY.md § "Layer 2: Redis"
    """

    def test_initialize_merges_environ_over_dotenv(self) -> None:
        """Values from os.environ must replace .env values during initialize()."""
        dotenv = {"KEY_A": "dotenv_a", "KEY_B": "dotenv_b"}

        with (
            patch("tastytrade.config.manager.redis.Redis") as mock_redis_cls,
            patch(
                "tastytrade.config.manager.dotenv_values",
                return_value=dotenv.copy(),
            ),
            patch.dict(os.environ, {"KEY_A": "environ_a"}, clear=False),
        ):
            manager = RedisConfigManager(env_file="/dev/null")
            mock_client = mock_redis_cls.return_value

            manager.initialize(force=True)

            # Verify hset was called with environ override for KEY_A
            call_args = mock_client.hset.call_args
            mapping = call_args[1].get("mapping") or call_args[0][1]
            assert mapping["KEY_A"] == "environ_a"
            assert mapping["KEY_B"] == "dotenv_b"

    def test_initialize_does_not_inject_extra_environ_keys(self) -> None:
        """initialize() should only override keys that exist in .env,
        not inject arbitrary os.environ keys into Redis."""
        dotenv = {"EXISTING_KEY": "from_dotenv"}

        with (
            patch("tastytrade.config.manager.redis.Redis") as mock_redis_cls,
            patch(
                "tastytrade.config.manager.dotenv_values",
                return_value=dotenv.copy(),
            ),
            patch.dict(os.environ, {"UNRELATED_KEY": "should_not_appear"}, clear=False),
        ):
            manager = RedisConfigManager(env_file="/dev/null")
            mock_client = mock_redis_cls.return_value

            manager.initialize(force=True)

            call_args = mock_client.hset.call_args
            mapping = call_args[1].get("mapping") or call_args[0][1]
            assert "UNRELATED_KEY" not in mapping


# ---------------------------------------------------------------------------
# 5. Explicit parameter — highest priority for bootstrap
#
# See docs/SERVICE_DISCOVERY.md § "Layer 1: os.environ"
# ---------------------------------------------------------------------------


class TestExplicitParameterPrecedence:
    """Explicit constructor parameters must override everything else.

    This allows programmatic overrides in tests and special configurations.
    """

    def test_explicit_host_overrides_environ_and_dotenv(self) -> None:
        """redis_host parameter must override os.environ and .env values."""
        with (
            patch("tastytrade.config.manager.redis.Redis") as mock_redis,
            patch(
                "tastytrade.config.manager.dotenv_values",
                return_value={"REDIS_HOST": "from-dotenv"},
            ),
            patch.dict(os.environ, {"REDIS_HOST": "from-environ"}, clear=False),
        ):
            RedisConfigManager(redis_host="explicit-host", env_file="/dev/null")
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "explicit-host"


# ---------------------------------------------------------------------------
# 6. RedisEventProcessor — consistent with config manager defaults
#
# See docs/SERVICE_DISCOVERY.md § "Files Involved"
# ---------------------------------------------------------------------------


class TestRedisEventProcessorDefaults:
    """RedisEventProcessor must follow the same service discovery contract
    as the config manager: os.environ → code default (localhost).

    Reference: docs/SERVICE_DISCOVERY.md § "Layer 3: Code defaults"
    """

    def test_defaults_to_localhost(self) -> None:
        """With no env vars, RedisEventProcessor must connect to localhost."""
        env_clean = {k: v for k, v in os.environ.items() if k != "REDIS_HOST"}
        with (
            patch("tastytrade.messaging.processors.redis.aioredis.Redis") as mock_redis,
            patch.dict(os.environ, env_clean, clear=True),
        ):
            from tastytrade.messaging.processors.redis import RedisEventProcessor

            RedisEventProcessor()
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "localhost"

    def test_respects_environ_override(self) -> None:
        """REDIS_HOST in os.environ must override the localhost default."""
        with (
            patch("tastytrade.messaging.processors.redis.aioredis.Redis") as mock_redis,
            patch.dict(os.environ, {"REDIS_HOST": "redis"}, clear=False),
        ):
            from tastytrade.messaging.processors.redis import RedisEventProcessor

            RedisEventProcessor()
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "redis"


# ---------------------------------------------------------------------------
# 7. RedisSubscriptionStore — consistent defaults
#
# See docs/SERVICE_DISCOVERY.md § "Files Involved"
# ---------------------------------------------------------------------------


class TestRedisSubscriptionStoreDefaults:
    """RedisSubscriptionStore must default to localhost for host compatibility.

    Reference: docs/SERVICE_DISCOVERY.md § "Layer 3: Code defaults"
    """

    def test_defaults_to_localhost(self) -> None:
        env_clean = {k: v for k, v in os.environ.items() if k != "REDIS_HOST"}
        with (
            patch("tastytrade.connections.subscription.redis.Redis") as mock_redis,
            patch.dict(os.environ, env_clean, clear=True),
        ):
            from tastytrade.connections.subscription import RedisSubscriptionStore

            RedisSubscriptionStore()
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "localhost"

    def test_respects_environ_override(self) -> None:
        with (
            patch("tastytrade.connections.subscription.redis.Redis") as mock_redis,
            patch.dict(os.environ, {"REDIS_HOST": "redis"}, clear=False),
        ):
            from tastytrade.connections.subscription import RedisSubscriptionStore

            RedisSubscriptionStore()
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs["host"] == "redis"
