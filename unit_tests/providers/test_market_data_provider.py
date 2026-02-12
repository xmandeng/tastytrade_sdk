"""Tests for MarketDataProvider."""

from datetime import date, datetime
from unittest.mock import MagicMock

import pandas as pd
import polars as pl
import pytest

from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.analytics.visualizations.models import VerticalLine
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


# --- download_signals tests ---

_SIGNAL_ROW = {
    "result": ["_result"],
    "table": [0],
    "_start": [pd.Timestamp("2026-02-11T14:00:00Z")],
    "_stop": [pd.Timestamp("2026-02-11T21:00:00Z")],
    "_time": [pd.Timestamp("2026-02-11T15:05:00Z")],
    "_measurement": ["TradeSignal"],
    "eventSymbol": ["SPX{=5m}"],
    "event_type": ["trade_signal"],
    "start_time": ["2026-02-11T15:05:00"],
    "label": ["OPEN BEARISH"],
    "color": ["red"],
    "line_width": [1.0],
    "line_dash": ["dot"],
    "opacity": [0.7],
    "show_label": [True],
    "label_font_size": [11.0],
    "signal_type": ["OPEN"],
    "direction": ["BEARISH"],
    "engine": ["HullMacdEngine"],
    "hull_direction": ["Down"],
    "hull_value": [6973.12],
    "macd_value": [5.3139],
    "macd_signal": [5.4582],
    "macd_histogram": [-0.1443],
    "close_price": [6948.23],
    "trigger": ["confluence"],
}


def _mock_query_api(return_df: pd.DataFrame) -> MagicMock:
    """Create a mock influx client whose query_api().query_data_frame() returns *return_df*."""
    mock_influx = MagicMock()
    mock_influx.query_api.return_value.query_data_frame.return_value = return_df
    return mock_influx


def test_download_signals_returns_list(monkeypatch: pytest.MonkeyPatch):
    """Mock query_data_frame, assert list[TradeSignal] returned."""
    monkeypatch.setattr(
        "tastytrade.providers.market.config",
        MagicMock(get=MagicMock(return_value="test-bucket")),
    )
    mock_influx = _mock_query_api(pd.DataFrame(_SIGNAL_ROW))
    provider = MarketDataProvider(data_feed=MagicMock(), influx=mock_influx)

    result = provider.download_signals(
        symbol="SPX{=5m}",
        start=datetime(2026, 2, 11, 14, 0),
        stop=datetime(2026, 2, 11, 21, 0),
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], TradeSignal)
    assert result[0].direction == "BEARISH"
    assert result[0].signal_type == "OPEN"
    assert result[0].eventSymbol == "SPX{=5m}"


def test_download_signals_empty_returns_empty_list(monkeypatch: pytest.MonkeyPatch):
    """Mock empty DataFrame, assert empty list returned."""
    monkeypatch.setattr(
        "tastytrade.providers.market.config",
        MagicMock(get=MagicMock(return_value="test-bucket")),
    )
    mock_influx = _mock_query_api(pd.DataFrame())
    provider = MarketDataProvider(data_feed=MagicMock(), influx=mock_influx)

    result = provider.download_signals(
        symbol="SPX{=5m}",
        start=datetime(2026, 2, 11, 14, 0),
        stop=datetime(2026, 2, 11, 21, 0),
    )

    assert result == []


def test_download_signals_filters_to_valid_fields(monkeypatch: pytest.MonkeyPatch):
    """Verify extra columns from InfluxDB metadata are dropped."""
    monkeypatch.setattr(
        "tastytrade.providers.market.config",
        MagicMock(get=MagicMock(return_value="test-bucket")),
    )
    row_with_extra = {**_SIGNAL_ROW, "extra_influx_col": ["should_be_dropped"]}
    mock_influx = _mock_query_api(pd.DataFrame(row_with_extra))
    provider = MarketDataProvider(data_feed=MagicMock(), influx=mock_influx)

    result = provider.download_signals(
        symbol="SPX{=5m}",
        start=datetime(2026, 2, 11, 14, 0),
        stop=datetime(2026, 2, 11, 21, 0),
    )

    assert len(result) == 1
    assert isinstance(result[0], TradeSignal)


def test_download_signals_parses_start_time(monkeypatch: pytest.MonkeyPatch):
    """Verify ISO string start_time is parsed back to datetime."""
    monkeypatch.setattr(
        "tastytrade.providers.market.config",
        MagicMock(get=MagicMock(return_value="test-bucket")),
    )
    mock_influx = _mock_query_api(pd.DataFrame(_SIGNAL_ROW))
    provider = MarketDataProvider(data_feed=MagicMock(), influx=mock_influx)

    result = provider.download_signals(
        symbol="SPX{=5m}",
        start=datetime(2026, 2, 11, 14, 0),
        stop=datetime(2026, 2, 11, 21, 0),
    )

    assert isinstance(result[0].start_time, datetime)
    assert result[0].start_time == datetime(2026, 2, 11, 15, 5, 0)


def test_download_signals_uses_correct_measurement(monkeypatch: pytest.MonkeyPatch):
    """Verify the Flux query contains the correct measurement name."""
    monkeypatch.setattr(
        "tastytrade.providers.market.config",
        MagicMock(get=MagicMock(return_value="test-bucket")),
    )
    mock_influx = _mock_query_api(pd.DataFrame(_SIGNAL_ROW))
    provider = MarketDataProvider(data_feed=MagicMock(), influx=mock_influx)

    provider.download_signals(
        symbol="SPX{=5m}",
        start=datetime(2026, 2, 11, 14, 0),
        stop=datetime(2026, 2, 11, 21, 0),
    )

    query_call = mock_influx.query_api.return_value.query_data_frame
    query_call.assert_called_once()
    flux_query = query_call.call_args[0][0]
    assert '"TradeSignal"' in flux_query


def test_to_vertical_line_preserves_fields():
    """Verify to_vertical_line() maps all shared BaseAnnotation fields."""
    signal = TradeSignal(
        eventSymbol="SPX{=5m}",
        start_time=datetime(2026, 2, 11, 15, 5),
        label="OPEN BEARISH",
        color="red",
        line_width=2.0,
        line_dash="dot",
        opacity=0.5,
        show_label=True,
        label_font_size=12.0,
        signal_type="OPEN",
        direction="BEARISH",
        engine="HullMacdEngine",
        hull_direction="Down",
        hull_value=6973.12,
        macd_value=5.3139,
        macd_signal=5.4582,
        macd_histogram=-0.1443,
        close_price=6948.23,
        trigger="confluence",
    )

    vline = signal.to_vertical_line()

    assert vline.eventSymbol == signal.eventSymbol
    assert vline.start_time == signal.start_time
    assert vline.label == signal.label
    assert vline.color == signal.color
    assert vline.line_width == signal.line_width
    assert vline.line_dash == signal.line_dash
    assert vline.opacity == signal.opacity
    assert vline.show_label == signal.show_label
    assert vline.label_font_size == signal.label_font_size


def test_to_vertical_line_returns_correct_type():
    """Assert to_vertical_line() returns a VerticalLine instance."""
    signal = TradeSignal(
        eventSymbol="SPX{=5m}",
        start_time=datetime(2026, 2, 11, 15, 5),
        label="CLOSE BULLISH",
        signal_type="CLOSE",
        direction="BULLISH",
        engine="HullMacdEngine",
        hull_direction="Up",
        hull_value=6950.0,
        macd_value=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        close_price=6955.0,
        trigger="hull",
    )

    result = signal.to_vertical_line()

    assert isinstance(result, VerticalLine)
