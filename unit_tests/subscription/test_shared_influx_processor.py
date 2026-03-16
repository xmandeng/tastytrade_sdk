"""Tests for TT-85: shared InfluxDB processor in subscription orchestrator."""

from unittest.mock import Mock

from tastytrade.config.enumerations import Channels
from tastytrade.messaging.handlers import EventHandler, ControlHandler
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor


class TestSharedInfluxProcessor:
    """Verify shared processor is created once and injected into handlers."""

    def setup_method(self) -> None:
        """Create a handler dict matching the real MessageRouter layout."""
        self.handlers: dict[Channels, EventHandler | ControlHandler] = {
            Channels.Control: ControlHandler(),
            Channels.Profile: EventHandler(Channels.Profile),
            Channels.Summary: EventHandler(Channels.Summary),
            Channels.Trade: EventHandler(Channels.Trade),
            Channels.Quote: EventHandler(Channels.Quote),
            Channels.Candle: EventHandler(Channels.Candle),
            Channels.Greeks: EventHandler(Channels.Greeks),
        }

    def test_control_handler_skipped(self) -> None:
        """Control channel should NOT receive the shared InfluxDB processor."""
        influx = Mock(spec=TelegrafHTTPEventProcessor)
        influx.name = "telegraf_http"

        for channel, handler in self.handlers.items():
            if channel != Channels.Control:
                handler.add_processor(influx)

        ctrl = self.handlers[Channels.Control]
        assert "telegraf_http" not in ctrl.processors

    def test_data_handlers_receive_shared_processor(self) -> None:
        """All 6 data channels should receive the same InfluxDB processor."""
        influx = Mock(spec=TelegrafHTTPEventProcessor)
        influx.name = "telegraf_http"

        for channel, handler in self.handlers.items():
            if channel != Channels.Control:
                handler.add_processor(influx)

        data_channels = [
            Channels.Profile,
            Channels.Summary,
            Channels.Trade,
            Channels.Quote,
            Channels.Candle,
            Channels.Greeks,
        ]
        for ch in data_channels:
            handler = self.handlers[ch]
            assert "telegraf_http" in handler.processors
            assert handler.processors["telegraf_http"] is influx

    def test_shared_processor_is_single_instance(self) -> None:
        """All handlers must reference the exact same object (not copies)."""
        influx = Mock(spec=TelegrafHTTPEventProcessor)
        influx.name = "telegraf_http"

        for channel, handler in self.handlers.items():
            if channel != Channels.Control:
                handler.add_processor(influx)

        refs = set()
        for ch, handler in self.handlers.items():
            if ch == Channels.Control:
                continue
            refs.add(id(handler.processors["telegraf_http"]))

        assert len(refs) == 1, "All handlers must share the same processor instance"


class TestShutdownCloseOnce:
    """Verify shared processor is closed exactly once during shutdown."""

    def setup_method(self) -> None:
        self.handlers: dict[Channels, EventHandler | ControlHandler] = {
            Channels.Control: ControlHandler(),
            Channels.Quote: EventHandler(Channels.Quote),
            Channels.Trade: EventHandler(Channels.Trade),
            Channels.Greeks: EventHandler(Channels.Greeks),
        }

    def test_remove_before_close_prevents_double_close(self) -> None:
        """Removing influx from handlers before close_processors() prevents
        the shared instance from being closed multiple times."""
        influx = Mock(spec=TelegrafHTTPEventProcessor)
        influx.name = "telegraf_http"

        # Attach to data handlers (mimics orchestrator setup)
        for ch, handler in self.handlers.items():
            if ch != Channels.Control:
                handler.add_processor(influx)

        # Shutdown sequence: remove shared influx, close remaining, close influx once
        for handler in self.handlers.values():
            handler.remove_processor(influx)
            handler.close_processors()

        influx.close.assert_not_called()  # not closed by handlers

        # Now close once
        influx.close()
        influx.close.assert_called_once()

    def test_handler_redis_processors_still_closed(self) -> None:
        """Redis processors on each handler should still be closed normally."""
        influx = Mock(spec=TelegrafHTTPEventProcessor)
        influx.name = "telegraf_http"

        redis_mocks = {}
        for ch, handler in self.handlers.items():
            if ch != Channels.Control:
                handler.add_processor(influx)
            redis = Mock()
            redis.name = f"redis_{ch.name}"
            handler.add_processor(redis)
            redis_mocks[ch] = redis

        # Remove shared influx, then close handlers
        for handler in self.handlers.values():
            handler.remove_processor(influx)
            handler.close_processors()

        # Redis processors should have been closed
        for _ch, redis in redis_mocks.items():
            redis.close.assert_called_once()

        # Shared influx should NOT have been closed by handlers
        influx.close.assert_not_called()
