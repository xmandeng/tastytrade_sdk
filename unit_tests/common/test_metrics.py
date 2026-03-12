"""Unit tests for OTLP metrics export module (event-driven design)."""

from unittest.mock import MagicMock, patch

import pytest

from tastytrade.common.metrics import (
    STATE_VALUES,
    init_metrics,
    record_reconnection,
    set_connection_status,
    set_order_count,
    set_position_count,
    set_subscription_count,
    shutdown_metrics,
)


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level state before each test."""
    import tastytrade.common.metrics as m

    m._meter_provider = None
    m._connection_gauge = None
    m._positions_gauge = None
    m._subscriptions_gauge = None
    m._orders_gauge = None
    m._reconnection_counter = None
    yield
    # Clean up after test
    if m._meter_provider is not None:
        try:
            m._meter_provider.shutdown()
        except Exception:
            pass
    m._meter_provider = None
    m._connection_gauge = None
    m._positions_gauge = None
    m._subscriptions_gauge = None
    m._orders_gauge = None
    m._reconnection_counter = None


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

    @patch("tastytrade.common.metrics.OTLPMetricExporter")
    def test_initializes_with_credentials(self, mock_exporter):
        env = {
            "GRAFANA_CLOUD_METRICS_INSTANCE_ID": "123",
            "GRAFANA_CLOUD_METRICS_TOKEN": "tok",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            result = init_metrics()

        assert result is not None
        mock_exporter.assert_called_once()
        call_kwargs = mock_exporter.call_args
        assert call_kwargs[1]["endpoint"] == "https://otlp.example.com/v1/metrics"

    @patch("tastytrade.common.metrics.OTLPMetricExporter")
    def test_idempotent(self, mock_exporter):
        env = {
            "GRAFANA_CLOUD_METRICS_INSTANCE_ID": "123",
            "GRAFANA_CLOUD_METRICS_TOKEN": "tok",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            first = init_metrics()
            second = init_metrics()

        assert first is second

    @patch("tastytrade.common.metrics.OTLPMetricExporter")
    def test_creates_all_instruments(self, mock_exporter):
        import tastytrade.common.metrics as m

        env = {
            "GRAFANA_CLOUD_METRICS_INSTANCE_ID": "123",
            "GRAFANA_CLOUD_METRICS_TOKEN": "tok",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            init_metrics()

        assert m._connection_gauge is not None
        assert m._positions_gauge is not None
        assert m._subscriptions_gauge is not None
        assert m._orders_gauge is not None
        assert m._reconnection_counter is not None


class TestSetConnectionStatus:
    def test_noop_without_init(self):
        set_connection_status("subscription", "connected")

    def test_sets_gauge_value(self):
        import tastytrade.common.metrics as m

        mock_gauge = MagicMock()
        m._connection_gauge = mock_gauge

        set_connection_status("subscription", "connected")
        mock_gauge.set.assert_called_with(1, {"service": "subscription"})

    def test_sets_error_value(self):
        import tastytrade.common.metrics as m

        mock_gauge = MagicMock()
        m._connection_gauge = mock_gauge

        set_connection_status("account_stream", "error")
        mock_gauge.set.assert_called_with(-1, {"service": "account_stream"})

    def test_sets_disconnected_value(self):
        import tastytrade.common.metrics as m

        mock_gauge = MagicMock()
        m._connection_gauge = mock_gauge

        set_connection_status("subscription", "disconnected")
        mock_gauge.set.assert_called_with(0, {"service": "subscription"})

    def test_unknown_state_defaults_to_error(self):
        import tastytrade.common.metrics as m

        mock_gauge = MagicMock()
        m._connection_gauge = mock_gauge

        set_connection_status("subscription", "bogus")
        mock_gauge.set.assert_called_with(-1, {"service": "subscription"})


class TestSetPositionCount:
    def test_noop_without_init(self):
        set_position_count(5)

    def test_sets_gauge_value(self):
        import tastytrade.common.metrics as m

        mock_gauge = MagicMock()
        m._positions_gauge = mock_gauge

        set_position_count(3)
        mock_gauge.set.assert_called_once_with(3)


class TestSetSubscriptionCount:
    def test_noop_without_init(self):
        set_subscription_count(10)

    def test_sets_gauge_value(self):
        import tastytrade.common.metrics as m

        mock_gauge = MagicMock()
        m._subscriptions_gauge = mock_gauge

        set_subscription_count(12)
        mock_gauge.set.assert_called_once_with(12)


class TestSetOrderCount:
    def test_noop_without_init(self):
        set_order_count(7)

    def test_sets_gauge_value(self):
        import tastytrade.common.metrics as m

        mock_gauge = MagicMock()
        m._orders_gauge = mock_gauge

        set_order_count(4)
        mock_gauge.set.assert_called_once_with(4)


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
        m._meter_provider = mock_provider

        shutdown_metrics()

        mock_provider.force_flush.assert_called_once()
        mock_provider.shutdown.assert_called_once()
        assert m._meter_provider is None

    def test_shutdown_idempotent(self):
        shutdown_metrics()
        shutdown_metrics()
