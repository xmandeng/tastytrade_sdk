"""Unit tests for OTLP metrics export module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from tastytrade.common.metrics import (
    ORDERS_KEY,
    POSITIONS_KEY,
    STATE_VALUES,
    init_metrics,
    observe_connection_status,
    observe_data_freshness,
    observe_order_count,
    observe_position_count,
    observe_subscription_count,
    record_reconnection,
    shutdown_metrics,
)


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level state before each test."""
    import tastytrade.common.metrics as m

    m._meter_provider = None
    m._redis_client = None
    m._reconnection_counter = None
    yield
    # Clean up after test
    if m._meter_provider is not None:
        try:
            m._meter_provider.shutdown()
        except Exception:
            pass
    m._meter_provider = None
    m._redis_client = None
    m._reconnection_counter = None


@pytest.fixture
def mock_redis():
    """Provide a mock Redis client."""
    import tastytrade.common.metrics as m

    client = MagicMock()
    m._redis_client = client
    return client


@pytest.fixture
def callback_options():
    """Provide a mock CallbackOptions."""
    return MagicMock()


class TestInitMetrics:
    def test_returns_none_without_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            result = init_metrics()
        assert result is None

    def test_returns_none_without_endpoint(self):
        env = {
            "GRAFANA_CLOUD_METRICS_INSTANCE_ID": "123",
            "GRAFANA_CLOUD_METRICS_TOKEN": "tok",
        }
        with patch.dict("os.environ", env, clear=True):
            result = init_metrics()
        assert result is None

    def test_returns_none_without_token(self):
        env = {
            "GRAFANA_CLOUD_METRICS_INSTANCE_ID": "123",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            result = init_metrics()
        assert result is None

    @patch("tastytrade.common.metrics.redis.Redis.from_url")
    @patch("tastytrade.common.metrics.OTLPMetricExporter")
    def test_initializes_with_credentials(self, mock_exporter, mock_from_url):
        env = {
            "GRAFANA_CLOUD_METRICS_INSTANCE_ID": "123",
            "GRAFANA_CLOUD_METRICS_TOKEN": "tok",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example.com",
        }
        mock_from_url.return_value = MagicMock()

        with patch.dict("os.environ", env, clear=True):
            result = init_metrics()

        assert result is not None
        mock_exporter.assert_called_once()
        call_kwargs = mock_exporter.call_args
        assert call_kwargs[1]["endpoint"] == "https://otlp.example.com/v1/metrics"

    @patch("tastytrade.common.metrics.redis.Redis.from_url")
    @patch("tastytrade.common.metrics.OTLPMetricExporter")
    def test_idempotent(self, mock_exporter, mock_from_url):
        env = {
            "GRAFANA_CLOUD_METRICS_INSTANCE_ID": "123",
            "GRAFANA_CLOUD_METRICS_TOKEN": "tok",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example.com",
        }
        mock_from_url.return_value = MagicMock()

        with patch.dict("os.environ", env, clear=True):
            first = init_metrics()
            second = init_metrics()

        assert first is second


class TestObserveConnectionStatus:
    def test_returns_empty_without_redis(self, callback_options):
        result = observe_connection_status(callback_options)
        assert result == []

    def test_reads_both_services(self, mock_redis, callback_options):
        mock_redis.hgetall.side_effect = [
            {"state": "connected", "timestamp": "2026-03-11T00:00:00Z"},
            {"state": "error", "timestamp": "2026-03-11T00:00:00Z", "error": "timeout"},
        ]

        result = observe_connection_status(callback_options)

        assert len(result) == 2
        assert result[0].value == 1  # connected
        assert result[0].attributes == {"service": "subscription"}
        assert result[1].value == -1  # error
        assert result[1].attributes == {"service": "account_stream"}

    def test_defaults_to_disconnected_when_empty(self, mock_redis, callback_options):
        mock_redis.hgetall.return_value = {}

        result = observe_connection_status(callback_options)

        assert len(result) == 2
        for obs in result:
            assert obs.value == 0  # disconnected

    def test_handles_redis_error(self, mock_redis, callback_options):
        mock_redis.hgetall.side_effect = Exception("connection refused")

        result = observe_connection_status(callback_options)

        assert len(result) == 2
        # First call fails, second also fails
        assert all(obs.value == -1 for obs in result)


class TestObservePositionCount:
    def test_returns_empty_without_redis(self, callback_options):
        result = observe_position_count(callback_options)
        assert result == []

    def test_returns_count(self, mock_redis, callback_options):
        mock_redis.hlen.return_value = 5

        result = observe_position_count(callback_options)

        assert len(result) == 1
        assert result[0].value == 5
        mock_redis.hlen.assert_called_once_with(POSITIONS_KEY)

    def test_handles_redis_error(self, mock_redis, callback_options):
        mock_redis.hlen.side_effect = Exception("connection refused")

        result = observe_position_count(callback_options)

        assert len(result) == 1
        assert result[0].value == 0


class TestObserveSubscriptionCount:
    def test_returns_empty_without_redis(self, callback_options):
        result = observe_subscription_count(callback_options)
        assert result == []

    def test_counts_active_only(self, mock_redis, callback_options):
        mock_redis.hgetall.return_value = {
            "AAPL": json.dumps({"active": True, "last_update": "2026-03-11T00:00:00"}),
            "MSFT": json.dumps({"active": True, "last_update": "2026-03-11T00:00:00"}),
            "GOOG": json.dumps({"active": False, "last_update": "2026-03-11T00:00:00"}),
        }

        result = observe_subscription_count(callback_options)

        assert len(result) == 1
        assert result[0].value == 2

    def test_handles_malformed_json(self, mock_redis, callback_options):
        mock_redis.hgetall.return_value = {
            "AAPL": json.dumps({"active": True}),
            "BAD": "not-json{{{",
        }

        result = observe_subscription_count(callback_options)

        assert result[0].value == 1

    def test_handles_redis_error(self, mock_redis, callback_options):
        mock_redis.hgetall.side_effect = Exception("connection refused")

        result = observe_subscription_count(callback_options)

        assert result[0].value == 0


class TestObserveOrderCount:
    def test_returns_empty_without_redis(self, callback_options):
        result = observe_order_count(callback_options)
        assert result == []

    def test_returns_count(self, mock_redis, callback_options):
        mock_redis.hlen.return_value = 3

        result = observe_order_count(callback_options)

        assert len(result) == 1
        assert result[0].value == 3
        mock_redis.hlen.assert_called_once_with(ORDERS_KEY)


class TestObserveDataFreshness:
    def test_returns_empty_without_redis(self, callback_options):
        result = observe_data_freshness(callback_options)
        assert result == []

    def test_calculates_age_per_feed_type(self, mock_redis, callback_options):
        mock_redis.hgetall.return_value = {
            "AAPL": json.dumps(
                {
                    "active": True,
                    "last_update": "2026-03-11T10:00:00+00:00",
                    "metadata": {"feed_type": "Ticker"},
                }
            ),
            "AAPL{=1d}": json.dumps(
                {
                    "active": True,
                    "last_update": "2026-03-11T09:00:00+00:00",
                    "metadata": {"feed_type": "Candle"},
                }
            ),
        }

        result = observe_data_freshness(callback_options)

        assert len(result) == 2
        feed_types = {obs.attributes["feed_type"] for obs in result}
        assert feed_types == {"Ticker", "Candle"}
        for obs in result:
            assert obs.value >= 0

    def test_skips_inactive_subscriptions(self, mock_redis, callback_options):
        mock_redis.hgetall.return_value = {
            "AAPL": json.dumps(
                {
                    "active": False,
                    "last_update": "2026-03-11T10:00:00+00:00",
                    "metadata": {"feed_type": "Ticker"},
                }
            ),
        }

        result = observe_data_freshness(callback_options)

        assert result == []

    def test_handles_redis_error(self, mock_redis, callback_options):
        mock_redis.hgetall.side_effect = Exception("connection refused")

        result = observe_data_freshness(callback_options)

        assert result == []


class TestStateValues:
    def test_state_mapping(self):
        assert STATE_VALUES["connected"] == 1
        assert STATE_VALUES["disconnected"] == 0
        assert STATE_VALUES["error"] == -1


class TestRecordReconnection:
    def test_noop_when_counter_not_initialized(self):
        record_reconnection("subscription")

    def test_increments_counter(self):
        import tastytrade.common.metrics as m

        mock_counter = MagicMock()
        m._reconnection_counter = mock_counter

        record_reconnection("account_stream")

        mock_counter.add.assert_called_once_with(1, {"service": "account_stream"})


class TestShutdownMetrics:
    def test_shutdown_with_provider(self):
        import tastytrade.common.metrics as m

        mock_provider = MagicMock()
        mock_client = MagicMock()
        m._meter_provider = mock_provider
        m._redis_client = mock_client

        shutdown_metrics()

        mock_provider.force_flush.assert_called_once()
        mock_provider.shutdown.assert_called_once()
        mock_client.close.assert_called_once()
        assert m._meter_provider is None
        assert m._redis_client is None

    def test_shutdown_idempotent(self):
        shutdown_metrics()
        shutdown_metrics()
