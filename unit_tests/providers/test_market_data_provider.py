"""Tests for MarketDataProvider."""

from datetime import date, datetime
from unittest.mock import MagicMock

import pandas as pd
import polars as pl
import pytest

from tastytrade.messaging.models.events import CandleEvent
from tastytrade.providers.market import MarketDataProvider


def _make_provider() -> MarketDataProvider:
    """Create a MarketDataProvider with mocked dependencies."""
    mock_feed = MagicMock()
    mock_influx = MagicMock()
    return MarketDataProvider(data_feed=mock_feed, influx=mock_influx)


_CANDLE_ROW = {
    "eventSymbol": ["SPX{=d}"],
    "time": [datetime(2026, 2, 7)],
    "open": [6000.0],
    "high": [6050.0],
    "low": [5980.0],
    "close": [6025.0],
    "volume": [1_000_000.0],
}


def test_get_daily_candle_returns_candle_event(monkeypatch: pytest.MonkeyPatch):
    """Mock download, assert CandleEvent returned with expected OHLCV."""
    provider = _make_provider()
    fake_df = pl.DataFrame(_CANDLE_ROW)
    mock_download = MagicMock(return_value=fake_df)
    monkeypatch.setattr(provider, "download", mock_download)

    result = provider.get_daily_candle("SPX{=m}", date(2026, 2, 7))

    assert isinstance(result, CandleEvent)
    assert result.open == 6000.0
    assert result.high == 6050.0
    assert result.low == 5980.0
    assert result.close == 6025.0
    assert result.volume == 1_000_000.0
    assert result.eventSymbol == "SPX{=d}"

    mock_download.assert_called_once()
    call_kwargs = mock_download.call_args
    assert call_kwargs.kwargs["symbol"] == "SPX{=d}"
    assert call_kwargs.kwargs["debug_mode"] is True


def test_get_daily_candle_empty_result_raises(monkeypatch: pytest.MonkeyPatch):
    """Mock empty DataFrame for all lookback days, assert ValueError raised."""
    provider = _make_provider()
    monkeypatch.setattr(provider, "download", MagicMock(return_value=pl.DataFrame()))

    with pytest.raises(ValueError, match="No valid daily candle found"):
        provider.get_daily_candle("SPX{=m}", date(2026, 2, 7))


def test_get_daily_candle_walks_back_past_holidays(monkeypatch: pytest.MonkeyPatch):
    """When target_date has no data (holiday), walk back to previous trading day."""
    provider = _make_provider()
    friday_row = {
        **_CANDLE_ROW,
        "time": [datetime(2026, 2, 13)],
    }
    friday_df = pl.DataFrame(friday_row)

    def mock_download(symbol, start, stop, debug_mode=False):
        # Feb 16 (Presidents' Day) → empty, Feb 13 (Friday) → data
        if start == date(2026, 2, 16):
            return pl.DataFrame()
        if start == date(2026, 2, 13):
            return friday_df
        return pl.DataFrame()

    monkeypatch.setattr(provider, "download", mock_download)

    result = provider.get_daily_candle("SPX{=5m}", date(2026, 2, 16))

    assert isinstance(result, CandleEvent)
    assert result.close == 6025.0


def test_get_daily_candle_skips_null_close(monkeypatch: pytest.MonkeyPatch):
    """When a day returns data but close is None, keep walking back."""
    provider = _make_provider()
    null_close_row = {
        "eventSymbol": ["SPX{=d}"],
        "time": [datetime(2026, 2, 14)],
        "open": [None],
        "high": [None],
        "low": [None],
        "close": [None],
        "volume": [None],
    }
    valid_row = {
        **_CANDLE_ROW,
        "time": [datetime(2026, 2, 13)],
    }

    def mock_download(symbol, start, stop, debug_mode=False):
        if start == date(2026, 2, 14):
            return pl.DataFrame(null_close_row)
        if start == date(2026, 2, 13):
            return pl.DataFrame(valid_row)
        return pl.DataFrame()

    monkeypatch.setattr(provider, "download", mock_download)

    result = provider.get_daily_candle("SPX{=5m}", date(2026, 2, 14))

    assert result.close == 6025.0


def test_download_empty_result_returns_empty_dataframe(
    monkeypatch: pytest.MonkeyPatch,
):
    """When InfluxDB returns no rows, download() returns an empty Polars DataFrame."""
    monkeypatch.setattr(
        "tastytrade.providers.market.config",
        MagicMock(get=MagicMock(return_value="test-bucket")),
    )
    mock_influx = MagicMock()
    mock_influx.query_api.return_value.query_data_frame.return_value = pd.DataFrame()
    provider = MarketDataProvider(data_feed=MagicMock(), influx=mock_influx)

    result = provider.download(
        symbol="SPX{=m}",
        start=datetime(2026, 2, 11, 14, 0),
        stop=datetime(2026, 2, 11, 21, 0),
        debug_mode=True,
    )

    assert isinstance(result, pl.DataFrame)
    assert result.is_empty()


def test_get_daily_candle_bare_symbol(monkeypatch: pytest.MonkeyPatch):
    """Call with bare symbol (no {=...} suffix), assert download called with SPX{=d}."""
    provider = _make_provider()
    fake_df = pl.DataFrame(_CANDLE_ROW)
    mock_download = MagicMock(return_value=fake_df)
    monkeypatch.setattr(provider, "download", mock_download)

    result = provider.get_daily_candle("SPX", date(2026, 2, 7))

    assert isinstance(result, CandleEvent)
    call_kwargs = mock_download.call_args
    assert call_kwargs.kwargs["symbol"] == "SPX{=d}"
