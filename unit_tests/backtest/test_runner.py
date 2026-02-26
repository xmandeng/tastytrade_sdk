"""Tests for BacktestRunner and BacktestReplay."""

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from tastytrade.backtest.models import BacktestConfig
from tastytrade.backtest.runner import BacktestRunner
from tastytrade.messaging.models.events import CandleEvent


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_config(
    symbol: str = "SPX",
    signal_interval: str = "5m",
    pricing_interval: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    backtest_id: str = "test-backtest-001",
) -> BacktestConfig:
    """Create a BacktestConfig with sensible defaults."""
    return BacktestConfig(
        backtest_id=backtest_id,
        symbol=symbol,
        signal_interval=signal_interval,
        pricing_interval=pricing_interval,
        start_date=start_date or date(2025, 1, 6),
        end_date=end_date or date(2025, 1, 10),
    )


def make_candle(
    symbol: str = "SPX{=5m}",
    time: datetime | None = None,
    close: float | None = 5900.0,
    open_: float = 5895.0,
    high: float = 5910.0,
    low: float = 5890.0,
    volume: float = 1000.0,
) -> CandleEvent:
    """Create a CandleEvent with sensible defaults."""
    return CandleEvent(
        eventSymbol=symbol,
        time=time or datetime(2025, 1, 6, 10, 0, 0),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_candle_df(candles: list[CandleEvent]) -> pl.DataFrame:
    """Convert a list of CandleEvents to a polars DataFrame.

    Mirrors the structure returned by MarketDataProvider.download()
    with debug_mode=True.
    """
    rows = [c.model_dump() for c in candles]
    return pl.DataFrame(rows)


def _make_replay(
    config: BacktestConfig | None = None,
    provider: MagicMock | None = None,
    redis_host: str = "localhost",
    redis_port: int = 6379,
):
    """Create a BacktestReplay with Redis mocked out.

    Returns (replay, mock_redis_instance) so callers can assert
    on Redis publish/close calls.
    """
    from tastytrade.backtest.replay import BacktestReplay

    cfg = config or make_config()
    prov = provider or MagicMock()
    mock_redis_instance = MagicMock()

    with patch("redis.Redis", return_value=mock_redis_instance):
        replay = BacktestReplay(
            config=cfg,
            provider=prov,
            redis_host=redis_host,
            redis_port=redis_port,
        )

    return replay, mock_redis_instance


# ---------------------------------------------------------------------------
# BacktestRunner tests
# ---------------------------------------------------------------------------


class TestBacktestRunnerSetup:
    """Tests for BacktestRunner.setup()."""

    @pytest.mark.asyncio
    async def test_setup_connects_and_subscribes_to_signal_channel(self) -> None:
        """setup() connects subscription and subscribes to signal channel."""
        config = make_config(symbol="SPX", signal_interval="5m")
        subscription = AsyncMock()
        engine = MagicMock()
        publisher = MagicMock()

        runner = BacktestRunner(
            config=config,
            subscription=subscription,
            engine=engine,
            publisher=publisher,
        )

        await runner.setup()

        subscription.connect.assert_awaited_once()
        subscription.subscribe.assert_any_await(
            "backtest:CandleEvent:SPX{=5m}",
            event_type=CandleEvent,
            on_update=engine.on_candle_event,
        )

    @pytest.mark.asyncio
    async def test_setup_subscribes_to_pricing_channel_when_different(self) -> None:
        """setup() subscribes to pricing channel when different from signal interval."""
        # 5m signal -> m pricing (auto-resolved, DXLink format)
        config = make_config(symbol="SPX", signal_interval="5m")
        subscription = AsyncMock()
        engine = MagicMock()
        publisher = MagicMock()

        runner = BacktestRunner(
            config=config,
            subscription=subscription,
            engine=engine,
            publisher=publisher,
        )

        await runner.setup()

        # Should subscribe to both signal and pricing channels
        assert subscription.subscribe.await_count == 2

        # Verify pricing channel subscription (DXLink: "m" not "1m")
        subscription.subscribe.assert_any_await(
            "backtest:CandleEvent:SPX{=m}",
            event_type=CandleEvent,
            on_update=publisher.buffer_pricing_candle,
        )

    @pytest.mark.asyncio
    async def test_setup_does_not_subscribe_pricing_when_same_interval(self) -> None:
        """setup() does NOT subscribe to pricing channel when same interval (e.g., m/m)."""
        # 1m signal -> m pricing (same after DXLink normalization)
        config = make_config(symbol="SPX", signal_interval="1m")
        subscription = AsyncMock()
        engine = MagicMock()
        publisher = MagicMock()

        runner = BacktestRunner(
            config=config,
            subscription=subscription,
            engine=engine,
            publisher=publisher,
        )

        await runner.setup()

        # Should only subscribe to signal channel (DXLink: "m" not "1m")
        assert subscription.subscribe.await_count == 1
        subscription.subscribe.assert_awaited_once_with(
            "backtest:CandleEvent:SPX{=m}",
            event_type=CandleEvent,
            on_update=engine.on_candle_event,
        )

    @pytest.mark.asyncio
    async def test_setup_subscribes_pricing_with_explicit_interval(self) -> None:
        """setup() uses explicit pricing_interval when provided (DXLink normalized)."""
        config = make_config(
            symbol="NVDA", signal_interval="15m", pricing_interval="1m"
        )
        subscription = AsyncMock()
        engine = MagicMock()
        publisher = MagicMock()

        runner = BacktestRunner(
            config=config,
            subscription=subscription,
            engine=engine,
            publisher=publisher,
        )

        await runner.setup()

        assert subscription.subscribe.await_count == 2
        subscription.subscribe.assert_any_await(
            "backtest:CandleEvent:NVDA{=15m}",
            event_type=CandleEvent,
            on_update=engine.on_candle_event,
        )
        # DXLink: "1m" normalizes to "m"
        subscription.subscribe.assert_any_await(
            "backtest:CandleEvent:NVDA{=m}",
            event_type=CandleEvent,
            on_update=publisher.buffer_pricing_candle,
        )


class TestBacktestRunnerSignals:
    """Tests for BacktestRunner.signals property."""

    def test_signals_returns_publisher_signals(self) -> None:
        """signals property returns publisher's signals list."""
        config = make_config()
        subscription = AsyncMock()
        engine = MagicMock()
        publisher = MagicMock()
        expected_signals = [MagicMock(), MagicMock()]
        publisher.signals = expected_signals

        runner = BacktestRunner(
            config=config,
            subscription=subscription,
            engine=engine,
            publisher=publisher,
        )

        assert runner.signals is expected_signals

    def test_signals_empty_when_no_signals_generated(self) -> None:
        """signals property returns empty list when publisher has no signals."""
        config = make_config()
        publisher = MagicMock()
        publisher.signals = []

        runner = BacktestRunner(
            config=config,
            subscription=AsyncMock(),
            engine=MagicMock(),
            publisher=publisher,
        )

        assert runner.signals == []


class TestBacktestRunnerStop:
    """Tests for BacktestRunner.stop()."""

    @pytest.mark.asyncio
    async def test_stop_closes_publisher_and_subscription(self) -> None:
        """stop() closes publisher and subscription."""
        config = make_config()
        subscription = AsyncMock()
        engine = MagicMock()
        publisher = MagicMock()
        publisher.signals = []

        runner = BacktestRunner(
            config=config,
            subscription=subscription,
            engine=engine,
            publisher=publisher,
        )

        await runner.stop()

        publisher.close.assert_called_once()
        subscription.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# BacktestReplay tests
# ---------------------------------------------------------------------------


class TestBacktestReplayRun:
    """Tests for BacktestReplay.run()."""

    def test_run_downloads_candles_for_both_timeframes(self) -> None:
        """run() downloads candles from MarketDataProvider for both timeframes."""
        config = make_config(
            symbol="SPX", signal_interval="5m", start_date=date(2025, 1, 6)
        )
        provider = MagicMock()

        signal_candles = [
            make_candle("SPX{=5m}", datetime(2025, 1, 6, 10, 0)),
        ]
        pricing_candles = [
            make_candle("SPX{=m}", datetime(2025, 1, 6, 10, 0)),
        ]

        def mock_download(
            symbol: str, start: date, stop: date, debug_mode: bool = False
        ) -> pl.DataFrame:
            if "5m" in symbol:
                return make_candle_df(signal_candles)
            elif "{=m}" in symbol:
                return make_candle_df(pricing_candles)
            return pl.DataFrame()

        provider.download = MagicMock(side_effect=mock_download)

        replay, _ = _make_replay(config=config, provider=provider)
        replay.run()

        # Should have called download twice: signal + pricing
        assert provider.download.call_count == 2

        # Verify signal download call
        signal_call = provider.download.call_args_list[0]
        assert signal_call.kwargs["symbol"] == "SPX{=5m}"

        # Verify pricing download call (DXLink: "m" not "1m")
        pricing_call = provider.download.call_args_list[1]
        assert pricing_call.kwargs["symbol"] == "SPX{=m}"

    def test_run_publishes_candles_to_correct_redis_channels(self) -> None:
        """run() publishes candles to correct Redis channels (backtest:CandleEvent:*)."""
        config = make_config(symbol="SPX", signal_interval="5m")
        provider = MagicMock()

        signal_candle = make_candle("SPX{=5m}", datetime(2025, 1, 6, 10, 0))
        pricing_candle = make_candle("SPX{=m}", datetime(2025, 1, 6, 10, 0))

        def mock_download(symbol: str, **kwargs) -> pl.DataFrame:
            if "5m" in symbol:
                return make_candle_df([signal_candle])
            elif "{=m}" in symbol:
                return make_candle_df([pricing_candle])
            return pl.DataFrame()

        provider.download = MagicMock(side_effect=mock_download)

        replay, mock_redis = _make_replay(config=config, provider=provider)
        replay.run()

        # Verify Redis publish was called with correct channels
        publish_calls = mock_redis.publish.call_args_list
        channels = [call.kwargs["channel"] for call in publish_calls]

        assert "backtest:CandleEvent:SPX{=5m}" in channels
        assert "backtest:CandleEvent:SPX{=m}" in channels

    def test_run_interleaves_candles_chronologically(self) -> None:
        """run() interleaves candles chronologically across timeframes."""
        config = make_config(symbol="SPX", signal_interval="5m")
        provider = MagicMock()

        t1 = datetime(2025, 1, 6, 10, 0)
        t2 = datetime(2025, 1, 6, 10, 1)
        t3 = datetime(2025, 1, 6, 10, 5)

        signal_candles = [
            make_candle("SPX{=5m}", t1, close=100.0),
            make_candle("SPX{=5m}", t3, close=102.0),
        ]
        pricing_candles = [
            make_candle("SPX{=m}", t2, close=101.0),
        ]

        def mock_download(symbol: str, **kwargs) -> pl.DataFrame:
            if "5m" in symbol:
                return make_candle_df(signal_candles)
            elif "{=m}" in symbol:
                return make_candle_df(pricing_candles)
            return pl.DataFrame()

        provider.download = MagicMock(side_effect=mock_download)

        replay, mock_redis = _make_replay(config=config, provider=provider)
        count = replay.run()

        # All 3 candles should be published
        assert count == 3

        # Verify chronological order via publish calls
        publish_calls = mock_redis.publish.call_args_list
        assert len(publish_calls) == 3

        # First candle at t1 (signal), second at t2 (pricing), third at t3 (signal)
        first_channel = publish_calls[0].kwargs["channel"]
        second_channel = publish_calls[1].kwargs["channel"]
        third_channel = publish_calls[2].kwargs["channel"]

        assert "SPX{=5m}" in first_channel
        assert "SPX{=m}" in second_channel
        assert "SPX{=5m}" in third_channel

    def test_run_returns_count_of_published_candles(self) -> None:
        """run() returns count of published candles."""
        config = make_config(symbol="SPX", signal_interval="5m")
        provider = MagicMock()

        candles = [
            make_candle("SPX{=5m}", datetime(2025, 1, 6, 10, i)) for i in range(5)
        ]

        def mock_download(symbol: str, **kwargs) -> pl.DataFrame:
            if "5m" in symbol:
                return make_candle_df(candles)
            return pl.DataFrame()

        provider.download = MagicMock(side_effect=mock_download)

        replay, _ = _make_replay(config=config, provider=provider)
        count = replay.run()

        assert count == 5

    def test_run_adds_warmup_buffer_before_start_date(self) -> None:
        """run() adds warmup buffer (3 extra days before start_date)."""
        start = date(2025, 1, 10)
        config = make_config(symbol="SPX", signal_interval="5m", start_date=start)
        provider = MagicMock()
        provider.download = MagicMock(return_value=pl.DataFrame())

        replay, _ = _make_replay(config=config, provider=provider)
        replay.run()

        # The first download call should have start = start_date - 3 days
        expected_warmup_start = start - timedelta(days=3)  # 2025-01-07
        signal_call = provider.download.call_args_list[0]
        actual_start = signal_call.kwargs["start"]
        assert actual_start == expected_warmup_start

    def test_run_skips_pricing_download_when_same_interval(self) -> None:
        """run() skips pricing download when same interval as signal."""
        # 1m signal -> m pricing (same after DXLink normalization)
        config = make_config(symbol="SPX", signal_interval="1m")
        provider = MagicMock()

        candles = [make_candle("SPX{=m}", datetime(2025, 1, 6, 10, 0))]
        provider.download = MagicMock(return_value=make_candle_df(candles))

        replay, _ = _make_replay(config=config, provider=provider)
        replay.run()

        # Only 1 download call (signal only, no pricing)
        assert provider.download.call_count == 1
        signal_call = provider.download.call_args_list[0]
        assert signal_call.kwargs["symbol"] == "SPX{=m}"

    def test_run_returns_zero_on_empty_data(self) -> None:
        """run() returns 0 when no candle data is available."""
        config = make_config(symbol="SPX", signal_interval="5m")
        provider = MagicMock()
        provider.download = MagicMock(return_value=pl.DataFrame())

        replay, mock_redis = _make_replay(config=config, provider=provider)
        count = replay.run()

        assert count == 0
        mock_redis.publish.assert_not_called()


class TestBacktestReplaySeedPriorClose:
    """Tests for BacktestReplay.seed_prior_close()."""

    def test_seed_prior_close_fetches_daily_candle(self) -> None:
        """seed_prior_close() fetches daily candle from provider."""
        config = make_config(symbol="SPX", start_date=date(2025, 1, 6))
        provider = MagicMock()

        daily_candle = make_candle("SPX{=d}", close=5880.50)
        provider.get_daily_candle = MagicMock(return_value=daily_candle)

        replay, _ = _make_replay(config=config, provider=provider)
        result = replay.seed_prior_close()

        assert result == 5880.50
        provider.get_daily_candle.assert_called_once_with(
            "SPX",
            date(2025, 1, 5),  # start_date - 1 day
        )

    def test_seed_prior_close_returns_none_on_value_error(self) -> None:
        """seed_prior_close() returns None on ValueError."""
        config = make_config(symbol="SPX", start_date=date(2025, 1, 6))
        provider = MagicMock()
        provider.get_daily_candle = MagicMock(
            side_effect=ValueError("No data available")
        )

        replay, _ = _make_replay(config=config, provider=provider)
        result = replay.seed_prior_close()

        assert result is None

    def test_seed_prior_close_returns_none_on_generic_exception(self) -> None:
        """seed_prior_close() returns None on generic Exception."""
        config = make_config(symbol="SPX", start_date=date(2025, 1, 6))
        provider = MagicMock()
        provider.get_daily_candle = MagicMock(
            side_effect=Exception("Connection refused")
        )

        replay, _ = _make_replay(config=config, provider=provider)
        result = replay.seed_prior_close()

        assert result is None

    def test_seed_prior_close_returns_none_when_close_is_none(self) -> None:
        """seed_prior_close() returns None when candle close is None."""
        config = make_config(symbol="SPX", start_date=date(2025, 1, 6))
        provider = MagicMock()

        daily_candle = make_candle("SPX{=d}", close=None)
        provider.get_daily_candle = MagicMock(return_value=daily_candle)

        replay, _ = _make_replay(config=config, provider=provider)
        result = replay.seed_prior_close()

        assert result is None


class TestBacktestReplayMergeAndSort:
    """Tests for BacktestReplay.merge_and_sort()."""

    def testmerge_and_sort_sorts_candles_by_time(self) -> None:
        """merge_and_sort() sorts candles by time."""
        config = make_config(symbol="SPX", signal_interval="5m")
        provider = MagicMock()

        t1 = datetime(2025, 1, 6, 10, 0)
        t2 = datetime(2025, 1, 6, 10, 5)
        t3 = datetime(2025, 1, 6, 10, 10)

        # Signal candles in non-chronological order
        signal_df = make_candle_df(
            [
                make_candle("SPX{=5m}", t3, close=103.0),
                make_candle("SPX{=5m}", t1, close=101.0),
            ]
        )
        pricing_df = make_candle_df(
            [
                make_candle("SPX{=1m}", t2, close=102.0),
            ]
        )

        replay, _ = _make_replay(config=config, provider=provider)
        candles = replay.merge_and_sort(signal_df, pricing_df)

        # Should be sorted chronologically
        assert len(candles) == 3
        assert candles[0].time == t1
        assert candles[1].time == t2
        assert candles[2].time == t3

    def testmerge_and_sort_handles_none_pricing_df(self) -> None:
        """merge_and_sort() works when pricing_df is None."""
        config = make_config(symbol="SPX", signal_interval="1m")
        provider = MagicMock()

        t1 = datetime(2025, 1, 6, 10, 0)
        t2 = datetime(2025, 1, 6, 10, 1)

        signal_df = make_candle_df(
            [
                make_candle("SPX{=1m}", t2, close=102.0),
                make_candle("SPX{=1m}", t1, close=101.0),
            ]
        )

        replay, _ = _make_replay(config=config, provider=provider)
        candles = replay.merge_and_sort(signal_df, None)

        assert len(candles) == 2
        assert candles[0].time == t1
        assert candles[1].time == t2

    def testmerge_and_sort_handles_empty_dataframes(self) -> None:
        """merge_and_sort() returns empty list for empty DataFrames."""
        config = make_config(symbol="SPX", signal_interval="5m")
        provider = MagicMock()

        replay, _ = _make_replay(config=config, provider=provider)
        candles = replay.merge_and_sort(pl.DataFrame(), None)

        assert candles == []

    def testmerge_and_sort_preserves_all_candle_fields(self) -> None:
        """merge_and_sort() produces CandleEvents with all fields intact."""
        config = make_config(symbol="SPX", signal_interval="5m")
        provider = MagicMock()

        t1 = datetime(2025, 1, 6, 10, 0)
        candle = make_candle(
            "SPX{=5m}",
            t1,
            close=5900.0,
            open_=5895.0,
            high=5910.0,
            low=5890.0,
            volume=1000.0,
        )
        signal_df = make_candle_df([candle])

        replay, _ = _make_replay(config=config, provider=provider)
        result = replay.merge_and_sort(signal_df, None)

        assert len(result) == 1
        assert result[0].eventSymbol == "SPX{=5m}"
        assert result[0].close == 5900.0
        assert result[0].open == 5895.0
        assert result[0].high == 5910.0
        assert result[0].low == 5890.0
        assert result[0].volume == 1000.0


class TestBacktestReplayClose:
    """Tests for BacktestReplay.close()."""

    def test_close_closes_redis_connection(self) -> None:
        """close() closes Redis connection."""
        config = make_config()
        provider = MagicMock()

        replay, mock_redis = _make_replay(config=config, provider=provider)
        replay.close()

        mock_redis.close.assert_called_once()


class TestBacktestReplayInit:
    """Tests for BacktestReplay initialization."""

    def test_init_uses_provided_redis_host_and_port(self) -> None:
        """BacktestReplay uses provided redis_host and redis_port."""
        config = make_config()
        provider = MagicMock()

        with patch("redis.Redis") as mock_redis_cls:
            mock_redis_cls.return_value = MagicMock()

            from tastytrade.backtest.replay import BacktestReplay

            BacktestReplay(
                config=config,
                provider=provider,
                redis_host="custom-host",
                redis_port=6380,
            )

        mock_redis_cls.assert_called_once_with(host="custom-host", port=6380)

    def test_init_defaults_redis_from_env(self) -> None:
        """BacktestReplay defaults redis config from environment variables."""
        config = make_config()
        provider = MagicMock()

        with (
            patch("redis.Redis") as mock_redis_cls,
            patch.dict("os.environ", {"REDIS_HOST": "env-host", "REDIS_PORT": "6381"}),
        ):
            mock_redis_cls.return_value = MagicMock()

            from tastytrade.backtest.replay import BacktestReplay

            BacktestReplay(config=config, provider=provider)

        mock_redis_cls.assert_called_once_with(host="env-host", port=6381)


class TestBacktestReplayDownloadCandles:
    """Tests for BacktestReplay.download_candles()."""

    def testdownload_candles_calls_provider_download(self) -> None:
        """download_candles() delegates to MarketDataProvider.download()."""
        config = make_config()
        provider = MagicMock()
        expected_df = make_candle_df([make_candle()])
        provider.download = MagicMock(return_value=expected_df)

        replay, _ = _make_replay(config=config, provider=provider)
        result = replay.download_candles(
            "SPX{=5m}", date(2025, 1, 3), date(2025, 1, 10)
        )

        provider.download.assert_called_once_with(
            symbol="SPX{=5m}",
            start=date(2025, 1, 3),
            stop=date(2025, 1, 10),
            debug_mode=True,
        )
        assert result.height == expected_df.height

    def testdownload_candles_returns_empty_df_on_error(self) -> None:
        """download_candles() returns empty DataFrame on provider error."""
        config = make_config()
        provider = MagicMock()
        provider.download = MagicMock(side_effect=Exception("InfluxDB error"))

        replay, _ = _make_replay(config=config, provider=provider)
        result = replay.download_candles(
            "SPX{=5m}", date(2025, 1, 3), date(2025, 1, 10)
        )

        assert result.is_empty()
