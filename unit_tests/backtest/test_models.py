"""Tests for backtest models (BacktestSignal, BacktestConfig) and BacktestPublisher.

Covers model construction, immutability, serialization, field defaults,
config resolution logic, and publisher signal enrichment / buffering.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.analytics.visualizations.models import BaseAnnotation
from tastytrade.backtest.models import (
    BacktestConfig,
    BacktestSignal,
    resolve_pricing_interval,
)
from tastytrade.backtest.publisher import BacktestPublisher
from tastytrade.messaging.models.events import BaseEvent, CandleEvent


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

_BASE_TIME = datetime(2026, 2, 10, 15, 0, 0, tzinfo=timezone.utc)


def make_trade_signal(
    symbol: str = "SPX{=5m}",
    signal_type: str = "OPEN",
    direction: str = "BULLISH",
    time_offset_minutes: int = 0,
    close_price: float = 5000.0,
) -> TradeSignal:
    """Create a minimal TradeSignal for testing."""
    ts = _BASE_TIME + timedelta(minutes=time_offset_minutes)
    return TradeSignal(
        eventSymbol=symbol,
        start_time=ts,
        label=f"{signal_type} {direction}",
        color="green" if direction == "BULLISH" else "red",
        signal_type=signal_type,
        direction=direction,
        engine="hull_macd",
        hull_direction="Up" if direction == "BULLISH" else "Down",
        hull_value=5010.0,
        macd_value=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        close_price=close_price,
        trigger="confluence",
    )


def make_candle(
    symbol: str = "SPX{=1m}",
    close: float | None = 5005.0,
    time_offset_minutes: int = 0,
) -> CandleEvent:
    """Create a minimal CandleEvent for pricing buffer tests."""
    ts = _BASE_TIME + timedelta(minutes=time_offset_minutes)
    return CandleEvent(
        eventSymbol=symbol,
        time=ts,
        open=close,
        high=close,
        low=close,
        close=close,
    )


def make_backtest_config(
    symbol: str = "SPX",
    signal_interval: str = "5m",
    pricing_interval: str | None = None,
    backtest_id: str = "test-run-001",
    source: str = "backtest",
) -> BacktestConfig:
    """Create a BacktestConfig with sensible defaults."""
    return BacktestConfig(
        backtest_id=backtest_id,
        symbol=symbol,
        signal_interval=signal_interval,
        pricing_interval=pricing_interval,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 1),
        source=source,
    )


def make_backtest_signal(
    symbol: str = "SPX{=5m}",
    backtest_id: str = "test-run-001",
    entry_price: float | None = 5005.0,
) -> BacktestSignal:
    """Create a minimal BacktestSignal for testing."""
    return BacktestSignal(
        eventSymbol=symbol,
        start_time=_BASE_TIME,
        label="OPEN BULLISH",
        color="green",
        signal_type="OPEN",
        direction="BULLISH",
        engine="hull_macd",
        hull_direction="Up",
        hull_value=5010.0,
        macd_value=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        close_price=5000.0,
        trigger="confluence",
        backtest_id=backtest_id,
        source="backtest",
        entry_price=entry_price,
        signal_interval="5m",
        pricing_interval="1m",
    )


# ===========================================================================
# BacktestSignal model tests
# ===========================================================================


class TestBacktestSignalInheritance:
    """BacktestSignal extends TradeSignal with backtest-specific metadata."""

    def test_extends_trade_signal(self):
        """BacktestSignal is a subclass of TradeSignal."""
        assert issubclass(BacktestSignal, TradeSignal)

    def test_extends_base_annotation(self):
        """BacktestSignal inherits from BaseAnnotation via TradeSignal."""
        assert issubclass(BacktestSignal, BaseAnnotation)

    def test_extends_base_event(self):
        """BacktestSignal inherits from BaseEvent via the full chain."""
        assert issubclass(BacktestSignal, BaseEvent)

    def test_all_trade_signal_fields_present(self):
        """All TradeSignal fields are present on a BacktestSignal instance."""
        sig = make_backtest_signal()
        trade_signal_fields = [
            "signal_type",
            "direction",
            "engine",
            "hull_direction",
            "hull_value",
            "macd_value",
            "macd_signal",
            "macd_histogram",
            "close_price",
            "trigger",
        ]
        for field in trade_signal_fields:
            assert hasattr(sig, field), f"Missing TradeSignal field: {field}"

    def test_all_base_annotation_fields_present(self):
        """All BaseAnnotation fields are present on a BacktestSignal instance."""
        sig = make_backtest_signal()
        annotation_fields = [
            "eventSymbol",
            "start_time",
            "label",
            "color",
            "line_width",
            "line_dash",
            "opacity",
        ]
        for field in annotation_fields:
            assert hasattr(sig, field), f"Missing BaseAnnotation field: {field}"


class TestBacktestSignalFields:
    """BacktestSignal has backtest-specific fields and correct defaults."""

    def test_has_backtest_id(self):
        sig = make_backtest_signal(backtest_id="abc-123")
        assert sig.backtest_id == "abc-123"

    def test_has_source(self):
        sig = make_backtest_signal()
        assert sig.source == "backtest"

    def test_has_entry_price(self):
        sig = make_backtest_signal(entry_price=5005.0)
        assert sig.entry_price == 5005.0

    def test_has_signal_interval(self):
        sig = make_backtest_signal()
        assert sig.signal_interval == "5m"

    def test_has_pricing_interval(self):
        sig = make_backtest_signal()
        assert sig.pricing_interval == "1m"

    def test_default_source_is_backtest(self):
        """Default source is 'backtest' when not explicitly provided."""
        sig = BacktestSignal(
            eventSymbol="SPX{=5m}",
            start_time=_BASE_TIME,
            label="test",
            signal_type="OPEN",
            direction="BULLISH",
            engine="hull_macd",
            hull_direction="Up",
            hull_value=5010.0,
            macd_value=1.0,
            macd_signal=0.5,
            macd_histogram=0.5,
            close_price=5000.0,
            trigger="confluence",
            backtest_id="run-1",
            signal_interval="5m",
            pricing_interval="1m",
        )
        assert sig.source == "backtest"

    def test_entry_price_can_be_none(self):
        """entry_price defaults to None and can remain None."""
        sig = make_backtest_signal(entry_price=None)
        assert sig.entry_price is None


class TestBacktestSignalEventType:
    """BacktestSignal has its own event_type for channel/measurement distinction."""

    def test_event_type_is_backtest_signal(self):
        """event_type must be 'backtest_signal', not 'trade_signal'."""
        sig = make_backtest_signal()
        assert sig.event_type == "backtest_signal"

    def test_event_type_differs_from_trade_signal(self):
        """BacktestSignal.event_type is distinct from TradeSignal.event_type."""
        trade = make_trade_signal()
        backtest = make_backtest_signal()
        assert trade.event_type == "trade_signal"
        assert backtest.event_type == "backtest_signal"
        assert trade.event_type != backtest.event_type


class TestBacktestSignalClassName:
    """Class name is critical for Redis channel and InfluxDB measurement routing."""

    def test_class_name_is_backtest_signal(self):
        """__class__.__name__ must be 'BacktestSignal' for channel routing."""
        sig = make_backtest_signal()
        assert sig.__class__.__name__ == "BacktestSignal"

    def test_class_name_differs_from_trade_signal(self):
        """BacktestSignal and TradeSignal have distinct __class__.__name__."""
        trade = make_trade_signal()
        backtest = make_backtest_signal()
        assert trade.__class__.__name__ == "TradeSignal"
        assert backtest.__class__.__name__ == "BacktestSignal"


class TestBacktestSignalImmutability:
    """BacktestSignal inherits frozen=True from BaseEvent."""

    def test_is_frozen(self):
        """BacktestSignal instances are immutable (frozen)."""
        sig = make_backtest_signal()
        with pytest.raises(ValidationError):
            sig.backtest_id = "changed"

    def test_cannot_mutate_entry_price(self):
        sig = make_backtest_signal(entry_price=5005.0)
        with pytest.raises(ValidationError):
            sig.entry_price = 9999.0

    def test_cannot_mutate_signal_type(self):
        sig = make_backtest_signal()
        with pytest.raises(ValidationError):
            sig.signal_type = "CLOSE"


class TestBacktestSignalProcessorSafety:
    """BacktestSignal is compatible with TelegrafHTTPEventProcessor."""

    def test_dict_items_yield_primitives_only(self):
        """Iterating __dict__.items() yields only str/int/float/bool values.

        The TelegrafHTTPEventProcessor calls point.field(attr, value) for
        each item in event.__dict__.items(). point.field() rejects datetime
        objects, so _ProcessorSafeDict must convert them.
        """
        sig = make_backtest_signal()
        for key, value in sig.__dict__.items():
            assert isinstance(value, (str, int, float, bool)), (
                f"Field {key!r} has non-primitive type {type(value).__name__} "
                f"in processor iteration"
            )

    def test_dict_items_skip_none_values(self):
        """None values are skipped in __dict__.items() iteration."""
        sig = make_backtest_signal(entry_price=None)
        keys = [k for k, _ in sig.__dict__.items()]
        assert "entry_price" not in keys

    def test_start_time_converted_to_iso_string(self):
        """start_time is a datetime but appears as ISO string in items()."""
        sig = make_backtest_signal()
        items_dict = dict(sig.__dict__.items())
        assert isinstance(items_dict["start_time"], str)
        # Verify it is a valid ISO 8601 string
        datetime.fromisoformat(items_dict["start_time"])


class TestBacktestSignalSerialization:
    """BacktestSignal can be serialized and deserialized via Pydantic."""

    def test_model_dump_json_roundtrip(self):
        """model_dump_json -> model_validate_json preserves all fields."""
        original = make_backtest_signal(entry_price=5005.0)
        json_str = original.model_dump_json()
        restored = BacktestSignal.model_validate_json(json_str)

        assert restored.backtest_id == original.backtest_id
        assert restored.source == original.source
        assert restored.entry_price == original.entry_price
        assert restored.signal_interval == original.signal_interval
        assert restored.pricing_interval == original.pricing_interval
        assert restored.signal_type == original.signal_type
        assert restored.direction == original.direction
        assert restored.engine == original.engine
        assert restored.eventSymbol == original.eventSymbol
        assert restored.event_type == original.event_type

    def test_model_dump_json_with_none_entry_price(self):
        """Serialization works when entry_price is None."""
        original = make_backtest_signal(entry_price=None)
        json_str = original.model_dump_json()
        restored = BacktestSignal.model_validate_json(json_str)
        assert restored.entry_price is None

    def test_model_dump_contains_backtest_fields(self):
        """model_dump() includes all backtest-specific fields."""
        sig = make_backtest_signal()
        dump = sig.model_dump()
        assert "backtest_id" in dump
        assert "source" in dump
        assert "entry_price" in dump
        assert "signal_interval" in dump
        assert "pricing_interval" in dump


# ===========================================================================
# BacktestConfig tests
# ===========================================================================


class TestBacktestConfigImmutability:
    """BacktestConfig is frozen."""

    def test_is_frozen(self):
        config = make_backtest_config()
        with pytest.raises(ValidationError):
            config.symbol = "NVDA"

    def test_cannot_mutate_signal_interval(self):
        config = make_backtest_config()
        with pytest.raises(ValidationError):
            config.signal_interval = "15m"


class TestBacktestConfigAutoId:
    """BacktestConfig auto-generates a UUID backtest_id when not provided."""

    def test_auto_generated_backtest_id(self):
        config = BacktestConfig(
            symbol="SPX",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        assert config.backtest_id is not None
        assert len(config.backtest_id) > 0

    def test_auto_generated_ids_are_unique(self):
        config1 = BacktestConfig(
            symbol="SPX",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        config2 = BacktestConfig(
            symbol="SPX",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        assert config1.backtest_id != config2.backtest_id

    def test_explicit_backtest_id_honored(self):
        config = make_backtest_config(backtest_id="my-custom-id")
        assert config.backtest_id == "my-custom-id"


class TestResolvePricingInterval:
    """resolve_pricing_interval maps signal intervals to finer pricing intervals."""

    @pytest.mark.parametrize(
        "signal_interval, expected_pricing",
        [
            ("1d", "1h"),
            ("4h", "1h"),
            ("1h", "15m"),
            ("30m", "5m"),
            ("15m", "5m"),
            ("5m", "1m"),
            ("1m", "1m"),
        ],
    )
    def test_default_mapping(self, signal_interval: str, expected_pricing: str):
        """Each signal interval maps to the correct default pricing interval."""
        result = resolve_pricing_interval(signal_interval)
        assert result == expected_pricing

    def test_explicit_override_takes_precedence(self):
        """When pricing_interval is explicitly provided, it overrides the default."""
        result = resolve_pricing_interval("5m", pricing_interval="30s")
        assert result == "30s"

    def test_explicit_none_uses_default(self):
        """Passing None explicitly uses the default mapping."""
        result = resolve_pricing_interval("5m", pricing_interval=None)
        assert result == "1m"

    def test_unknown_interval_returns_itself(self):
        """An unknown signal interval falls back to itself."""
        result = resolve_pricing_interval("2h")
        assert result == "2h"


class TestBacktestConfigProperties:
    """BacktestConfig derived properties produce correct symbol formats."""

    def test_signal_symbol(self):
        config = make_backtest_config(symbol="SPX", signal_interval="5m")
        assert config.signal_symbol == "SPX{=5m}"

    def test_signal_symbol_different_interval(self):
        config = make_backtest_config(symbol="NVDA", signal_interval="1h")
        assert config.signal_symbol == "NVDA{=1h}"

    def test_pricing_symbol_auto_resolved(self):
        """pricing_symbol uses auto-resolved pricing interval when not explicit."""
        config = make_backtest_config(symbol="SPX", signal_interval="5m")
        assert config.pricing_symbol == "SPX{=1m}"

    def test_pricing_symbol_explicit_override(self):
        config = make_backtest_config(
            symbol="SPX", signal_interval="5m", pricing_interval="30s"
        )
        assert config.pricing_symbol == "SPX{=30s}"

    def test_resolved_pricing_interval_auto(self):
        config = make_backtest_config(signal_interval="15m")
        assert config.resolved_pricing_interval == "5m"

    def test_resolved_pricing_interval_explicit(self):
        config = make_backtest_config(signal_interval="15m", pricing_interval="1m")
        assert config.resolved_pricing_interval == "1m"


class TestBacktestConfigDefaults:
    """BacktestConfig has correct defaults."""

    def test_default_engine_type(self):
        config = BacktestConfig(
            symbol="SPX",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        assert config.engine_type == "hull_macd"

    def test_default_source(self):
        config = BacktestConfig(
            symbol="SPX",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        assert config.source == "backtest"

    def test_default_signal_interval(self):
        config = BacktestConfig(
            symbol="SPX",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        assert config.signal_interval == "5m"

    def test_default_pricing_interval_is_none(self):
        config = BacktestConfig(
            symbol="SPX",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        assert config.pricing_interval is None


# ===========================================================================
# BacktestPublisher tests
# ===========================================================================


class TestBacktestPublisherConversion:
    """publish() converts TradeSignal to BacktestSignal with enrichment."""

    def test_publish_converts_trade_signal_to_backtest_signal(self):
        """publish() produces a BacktestSignal from a TradeSignal."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)
        signal = make_trade_signal()

        publisher.publish(signal)

        assert len(publisher.signals) == 1
        result = publisher.signals[0]
        assert isinstance(result, BacktestSignal)

    def test_publish_preserves_trade_signal_fields(self):
        """The converted BacktestSignal retains all original TradeSignal fields."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)
        signal = make_trade_signal(
            signal_type="CLOSE",
            direction="BEARISH",
            close_price=4950.0,
        )

        publisher.publish(signal)
        result = publisher.signals[0]

        assert result.signal_type == "CLOSE"
        assert result.direction == "BEARISH"
        assert result.close_price == 4950.0
        assert result.engine == signal.engine
        assert result.hull_direction == signal.hull_direction
        assert result.hull_value == signal.hull_value
        assert result.macd_value == signal.macd_value
        assert result.macd_signal == signal.macd_signal
        assert result.macd_histogram == signal.macd_histogram
        assert result.trigger == signal.trigger
        assert result.eventSymbol == signal.eventSymbol
        assert result.start_time == signal.start_time
        assert result.label == signal.label
        assert result.color == signal.color

    def test_publish_enriches_with_backtest_metadata(self):
        """BacktestSignal gets backtest_id, source, and intervals from config."""
        config = make_backtest_config(
            backtest_id="enrich-test-001",
            source="backtest",
            signal_interval="15m",
            pricing_interval="5m",
        )
        publisher = BacktestPublisher(config)
        signal = make_trade_signal()

        publisher.publish(signal)
        result = publisher.signals[0]

        assert result.backtest_id == "enrich-test-001"
        assert result.source == "backtest"
        assert result.signal_interval == "15m"
        assert result.pricing_interval == "5m"

    def test_publish_uses_resolved_pricing_interval(self):
        """When pricing_interval is None, the resolved value is used."""
        config = make_backtest_config(signal_interval="5m", pricing_interval=None)
        publisher = BacktestPublisher(config)
        signal = make_trade_signal()

        publisher.publish(signal)
        result = publisher.signals[0]

        # 5m signal interval resolves to 1m pricing
        assert result.pricing_interval == "1m"


class TestBacktestPublisherEntryPrice:
    """publish() looks up entry_price from the pricing candle buffer."""

    def test_entry_price_from_matching_candle(self):
        """Entry price is taken from the closest candle at or before signal time."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        # Buffer a candle at t=0 with close=5005
        publisher.buffer_pricing_candle(
            make_candle(close=5005.0, time_offset_minutes=0)
        )
        # Signal also at t=0
        signal = make_trade_signal(time_offset_minutes=0)
        publisher.publish(signal)

        assert publisher.signals[0].entry_price == 5005.0

    def test_entry_price_none_when_buffer_empty(self):
        """entry_price is None when no pricing candles have been buffered."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)
        signal = make_trade_signal()

        publisher.publish(signal)

        assert publisher.signals[0].entry_price is None

    def test_finds_closest_candle_at_or_before_signal_time(self):
        """Walks backward to find the most recent candle <= signal time."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        # Buffer candles at t=-10, t=-5, t=0, t=+5
        publisher.buffer_pricing_candle(
            make_candle(close=4990.0, time_offset_minutes=-10)
        )
        publisher.buffer_pricing_candle(
            make_candle(close=4995.0, time_offset_minutes=-5)
        )
        publisher.buffer_pricing_candle(
            make_candle(close=5000.0, time_offset_minutes=0)
        )
        publisher.buffer_pricing_candle(
            make_candle(close=5010.0, time_offset_minutes=5)
        )

        # Signal at t=+2 — closest candle at or before is t=0 (close=5000)
        signal = make_trade_signal(time_offset_minutes=2)
        publisher.publish(signal)

        assert publisher.signals[0].entry_price == 5000.0

    def test_entry_price_uses_exact_match_candle(self):
        """When a candle time exactly matches signal time, use it."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        publisher.buffer_pricing_candle(
            make_candle(close=4990.0, time_offset_minutes=-5)
        )
        publisher.buffer_pricing_candle(
            make_candle(close=5005.0, time_offset_minutes=0)
        )
        publisher.buffer_pricing_candle(
            make_candle(close=5010.0, time_offset_minutes=5)
        )

        signal = make_trade_signal(time_offset_minutes=0)
        publisher.publish(signal)

        assert publisher.signals[0].entry_price == 5005.0

    def test_entry_price_none_when_all_candles_after_signal(self):
        """entry_price is None when all buffered candles are after signal time."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        # All candles in the future relative to the signal
        publisher.buffer_pricing_candle(
            make_candle(close=5010.0, time_offset_minutes=5)
        )
        publisher.buffer_pricing_candle(
            make_candle(close=5020.0, time_offset_minutes=10)
        )

        signal = make_trade_signal(time_offset_minutes=0)
        publisher.publish(signal)

        assert publisher.signals[0].entry_price is None

    def test_entry_price_skips_candle_with_none_close(self):
        """Candles with close=None are skipped in entry price lookup."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        # Earlier candle has a valid close, later candle has None close
        publisher.buffer_pricing_candle(
            make_candle(close=4990.0, time_offset_minutes=-10)
        )
        publisher.buffer_pricing_candle(make_candle(close=None, time_offset_minutes=-5))

        signal = make_trade_signal(time_offset_minutes=0)
        publisher.publish(signal)

        # Should skip the None-close candle and use the earlier one
        assert publisher.signals[0].entry_price == 4990.0


class TestBacktestPublisherSignalAccumulation:
    """publish() appends signals to the internal list."""

    def test_signals_property_returns_accumulated_signals(self):
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        publisher.publish(make_trade_signal(time_offset_minutes=0))
        publisher.publish(make_trade_signal(time_offset_minutes=5))
        publisher.publish(make_trade_signal(time_offset_minutes=10))

        assert len(publisher.signals) == 3
        for sig in publisher.signals:
            assert isinstance(sig, BacktestSignal)

    def test_signals_initially_empty(self):
        config = make_backtest_config()
        publisher = BacktestPublisher(config)
        assert publisher.signals == []


class TestBacktestPublisherInnerPublisher:
    """publish() delegates to inner publisher when present."""

    def test_calls_inner_publisher_with_backtest_signal(self):
        """Inner publisher's publish() is called with the enriched BacktestSignal."""
        config = make_backtest_config()
        inner = MagicMock()
        publisher = BacktestPublisher(config, inner_publisher=inner)

        signal = make_trade_signal()
        publisher.publish(signal)

        inner.publish.assert_called_once()
        published_arg = inner.publish.call_args[0][0]
        assert isinstance(published_arg, BacktestSignal)

    def test_no_inner_publisher_does_not_raise(self):
        """publish() works without an inner publisher."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config, inner_publisher=None)
        signal = make_trade_signal()
        # Should not raise
        publisher.publish(signal)
        assert len(publisher.signals) == 1

    def test_inner_publisher_receives_backtest_metadata(self):
        """The BacktestSignal passed to inner publisher has enriched metadata."""
        config = make_backtest_config(backtest_id="inner-test-001")
        inner = MagicMock()
        publisher = BacktestPublisher(config, inner_publisher=inner)

        publisher.publish(make_trade_signal())

        published_arg = inner.publish.call_args[0][0]
        assert published_arg.backtest_id == "inner-test-001"


class TestBacktestPublisherNonTradeSignalEvents:
    """publish() handles non-TradeSignal events correctly."""

    def test_skips_non_trade_signal_events(self):
        """Non-TradeSignal events are not converted or accumulated."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        candle = make_candle()
        publisher.publish(candle)

        assert len(publisher.signals) == 0

    def test_forwards_non_trade_signal_to_inner_publisher(self):
        """Non-TradeSignal events are forwarded to inner publisher unchanged."""
        config = make_backtest_config()
        inner = MagicMock()
        publisher = BacktestPublisher(config, inner_publisher=inner)

        candle = make_candle()
        publisher.publish(candle)

        inner.publish.assert_called_once_with(candle)

    def test_non_trade_signal_no_inner_publisher_no_error(self):
        """Non-TradeSignal without inner publisher does not raise."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config, inner_publisher=None)

        candle = make_candle()
        # Should not raise
        publisher.publish(candle)
        assert len(publisher.signals) == 0


class TestBacktestPublisherBuffering:
    """buffer_pricing_candle() adds candles to the internal buffer."""

    def test_buffer_pricing_candle_accumulates(self):
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        publisher.buffer_pricing_candle(make_candle(time_offset_minutes=0))
        publisher.buffer_pricing_candle(make_candle(time_offset_minutes=1))
        publisher.buffer_pricing_candle(make_candle(time_offset_minutes=2))

        # Verify by publishing a signal and checking it uses buffered data
        signal = make_trade_signal(time_offset_minutes=2)
        publisher.publish(signal)
        assert publisher.signals[0].entry_price is not None

    def test_buffer_preserves_order(self):
        """Candles are stored in insertion order so backward search works."""
        config = make_backtest_config()
        publisher = BacktestPublisher(config)

        publisher.buffer_pricing_candle(
            make_candle(close=5000.0, time_offset_minutes=0)
        )
        publisher.buffer_pricing_candle(
            make_candle(close=5010.0, time_offset_minutes=5)
        )

        # Signal at t=5 should pick up the candle at t=5 (most recent at or before)
        signal = make_trade_signal(time_offset_minutes=5)
        publisher.publish(signal)
        assert publisher.signals[0].entry_price == 5010.0


class TestBacktestPublisherClose:
    """close() delegates to inner publisher."""

    def test_close_calls_inner_publisher(self):
        config = make_backtest_config()
        inner = MagicMock()
        publisher = BacktestPublisher(config, inner_publisher=inner)

        publisher.close()

        inner.close.assert_called_once()

    def test_close_without_inner_publisher(self):
        config = make_backtest_config()
        publisher = BacktestPublisher(config, inner_publisher=None)
        # Should not raise
        publisher.close()
