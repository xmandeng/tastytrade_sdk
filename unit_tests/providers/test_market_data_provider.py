"""Tests for MarketDataProvider.get_daily_candle()."""

from datetime import date, datetime
from unittest.mock import MagicMock

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
    """Mock empty DataFrame, assert ValueError raised."""
    provider = _make_provider()
    monkeypatch.setattr(provider, "download", MagicMock(return_value=pl.DataFrame()))

    with pytest.raises(ValueError, match="No daily candle found"):
        provider.get_daily_candle("SPX{=m}", date(2026, 2, 7))


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
