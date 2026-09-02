"""Two-tier candle channels: the configured fast pool rides the
firehose CandleFast channel; every other candle subscription defaults to
the conflated Candle channel."""

import json

import pytest

from tastytrade.config.configurations import CHANNEL_SPECS
from tastytrade.config.enumerations import Channels, EventTypes
from tastytrade.connections.routing import MessageRouter
from tastytrade.connections.sockets import (
    aggregation_period_for,
    candle_fast_pool,
    channel_for_candle,
)
from tastytrade.messaging.models.messages import FeedSetupModel


class TestFastPoolRouting:
    def test_default_pool_is_spx_1m_5m(self):
        assert candle_fast_pool() == {"SPX{=m}", "SPX{=5m}"}

    def test_pool_members_ride_fast_channel(self):
        assert channel_for_candle("SPX{=m}") == Channels.CandleFast
        assert channel_for_candle("SPX{=5m}") == Channels.CandleFast

    def test_everything_else_defaults_to_slow(self):
        for symbol in (
            "SPX{=15m}",
            "SPX{=30m}",
            "SPX{=h}",
            "SPX{=d}",
            "NVDA{=m}",
            "NVDA{=5m}",
            "QQQ{=5m}",
            "BTC/USD:CXTALP{=m}",
        ):
            assert channel_for_candle(symbol) == Channels.Candle, symbol

    def test_pool_is_configurable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CANDLE_FAST_POOL", "NVDA{=5m}, SPX{=5m}")
        assert channel_for_candle("NVDA{=5m}") == Channels.CandleFast
        assert channel_for_candle("SPX{=5m}") == Channels.CandleFast
        assert channel_for_candle("SPX{=m}") == Channels.Candle


class TestChannelSpecs:
    def test_fast_channel_spec_uses_candle_event_type(self):
        spec = CHANNEL_SPECS[Channels.CandleFast]
        assert spec.type == "Candle"  # dxFeed event type, not the channel name
        assert spec.event_type == EventTypes.Candle
        assert spec.fields == CHANNEL_SPECS[Channels.Candle].fields

    def test_tier_aggregation_defaults(self):
        assert aggregation_period_for(CHANNEL_SPECS[Channels.CandleFast]) == 0.1
        assert aggregation_period_for(CHANNEL_SPECS[Channels.Candle]) == 1.0
        assert aggregation_period_for(CHANNEL_SPECS[Channels.Quote]) == 0.1

    def test_tier_aggregation_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CANDLE_SLOW_AGGREGATION", "5.0")
        monkeypatch.setenv("CANDLE_FAST_AGGREGATION", "0.5")
        assert aggregation_period_for(CHANNEL_SPECS[Channels.Candle]) == 5.0
        assert aggregation_period_for(CHANNEL_SPECS[Channels.CandleFast]) == 0.5

    def test_feed_setup_wire_format_carries_aggregation(self):
        spec = CHANNEL_SPECS[Channels.CandleFast]
        payload = json.loads(
            FeedSetupModel(
                acceptAggregationPeriod=aggregation_period_for(spec),
                acceptEventFields={spec.type: spec.fields},
                channel=spec.channel.value,
            ).model_dump_json()
        )
        assert payload["channel"] == 13
        assert payload["acceptAggregationPeriod"] == 0.1
        assert "Candle" in payload["acceptEventFields"]


class TestRouting:
    def test_default_handlers_cover_both_candle_channels(self):
        handlers = MessageRouter.default_handlers
        assert Channels.CandleFast in handlers
        fast = handlers[Channels.CandleFast]
        slow = handlers[Channels.Candle]
        assert type(fast.feed_processor) is type(slow.feed_processor)
        assert fast.fields == slow.fields
