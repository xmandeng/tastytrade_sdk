"""Tests for time_series utility functions.

Two concerns:
  1. Pandas frequency alias mapping — pandas 3.0 removed 'T' (minutes) and
     deprecated lowercase 'd' (days). Each supported interval gets its own
     regression test so a future pandas upgrade can't silently break this.
  2. The gap-detection and forward-fill logic in prepare_and_fill_data.
"""

import pandas as pd
import pytest
from pandas import Timestamp

from tastytrade.utils.time_series import prepare_and_fill_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frame(timestamps: list[str], close: float | list[float]) -> pd.DataFrame:
    """Minimal CandleEvent DataFrame matching InfluxDB query_data_frame output.

    _time column is tz-aware UTC, matching what influxdb_client returns.
    """
    prices = close if isinstance(close, list) else [close] * len(timestamps)
    return pd.DataFrame(
        {
            "_time": pd.to_datetime(timestamps, utc=True),
            "close": prices,
            "open": prices,
            "high": prices,
            "low": prices,
        }
    )


# ---------------------------------------------------------------------------
# Pandas 3.0 frequency alias regression tests
#
# Each test exercises a single interval end-to-end through prepare_and_fill_data.
# If a future pandas upgrade re-breaks the alias mapping, exactly one test will
# fail and identify which interval is affected.
# ---------------------------------------------------------------------------


class TestPandasFrequencyAliases:
    """Regression: pandas 3.0 removed 'T' (minutes) and deprecated 'd' (days)."""

    def _frame_with_gap(self, start: str, gap_minutes: int) -> pd.DataFrame:
        """Two timestamps separated by 2× the interval — one gap in between."""
        base = pd.Timestamp(start, tz="UTC")
        end = base + pd.Timedelta(minutes=gap_minutes * 2)
        return _make_frame([str(base), str(end)], [100.0, 102.0])

    def test_1m_interval(self) -> None:
        df = self._frame_with_gap("2026-01-01T10:00:00+00:00", gap_minutes=1)
        result = prepare_and_fill_data(df, "1m")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_5m_interval(self) -> None:
        df = self._frame_with_gap("2026-01-01T10:00:00+00:00", gap_minutes=5)
        result = prepare_and_fill_data(df, "5m")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_15m_interval(self) -> None:
        df = self._frame_with_gap("2026-01-01T10:00:00+00:00", gap_minutes=15)
        result = prepare_and_fill_data(df, "15m")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_30m_interval(self) -> None:
        df = self._frame_with_gap("2026-01-01T10:00:00+00:00", gap_minutes=30)
        result = prepare_and_fill_data(df, "30m")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_1h_interval(self) -> None:
        base = pd.Timestamp("2026-01-01T10:00:00+00:00")
        end = base + pd.Timedelta(hours=2)
        df = _make_frame([str(base), str(end)], [100.0, 102.0])
        result = prepare_and_fill_data(df, "1h")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_1d_interval(self) -> None:
        df = _make_frame(
            ["2026-01-01T00:00:00+00:00", "2026-01-03T00:00:00+00:00"],
            [200.0, 210.0],
        )
        result = prepare_and_fill_data(df, "1d")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Gap-detection and forward-fill logic
# ---------------------------------------------------------------------------


class TestPrepareAndFillData:
    def test_missing_row_is_identified(self) -> None:
        """A single missing candle between two present ones is detected."""
        df = _make_frame(
            ["2026-01-01T10:00:00+00:00", "2026-01-01T10:10:00+00:00"],
            [100.0, 102.0],
        )
        result = prepare_and_fill_data(df, "5m")
        assert Timestamp("2026-01-01T10:05:00") in result.index

    def test_missing_row_forward_fills_value(self) -> None:
        """The gap row carries forward the preceding close value."""
        df = _make_frame(
            ["2026-01-01T10:00:00+00:00", "2026-01-01T10:10:00+00:00"],
            [100.0, 102.0],
        )
        result = prepare_and_fill_data(df, "5m")
        assert result.loc[Timestamp("2026-01-01T10:05:00"), "close"] == pytest.approx(
            100.0
        )

    def test_no_gaps_returns_empty_dataframe(self) -> None:
        """When every expected row exists there is nothing to fill."""
        df = _make_frame(
            [
                "2026-01-01T10:00:00+00:00",
                "2026-01-01T10:05:00+00:00",
                "2026-01-01T10:10:00+00:00",
            ],
            [100.0, 101.0, 102.0],
        )
        result = prepare_and_fill_data(df, "5m")
        assert result.empty

    def test_multiple_consecutive_gaps_all_filled(self) -> None:
        """Multiple consecutive missing candles are all included in output."""
        df = _make_frame(
            ["2026-01-01T10:00:00+00:00", "2026-01-01T10:30:00+00:00"],
            [50.0, 60.0],
        )
        result = prepare_and_fill_data(df, "10m")
        assert len(result) == 2
        assert Timestamp("2026-01-01T10:10:00") in result.index
        assert Timestamp("2026-01-01T10:20:00") in result.index

    def test_all_gaps_carry_forward_same_value(self) -> None:
        """Consecutive gaps all forward-fill from the last known value."""
        df = _make_frame(
            ["2026-01-01T10:00:00+00:00", "2026-01-01T10:30:00+00:00"],
            [50.0, 60.0],
        )
        result = prepare_and_fill_data(df, "10m")
        for ts in ["2026-01-01T10:10:00", "2026-01-01T10:20:00"]:
            assert result.loc[Timestamp(ts), "close"] == pytest.approx(50.0)

    def test_daily_gap_detected_and_filled(self) -> None:
        """A missing day is detected and forward-filled from the prior day."""
        df = _make_frame(
            ["2026-01-01T00:00:00+00:00", "2026-01-03T00:00:00+00:00"],
            [200.0, 210.0],
        )
        result = prepare_and_fill_data(df, "1d")
        assert Timestamp("2026-01-02") in result.index
        assert result.loc[Timestamp("2026-01-02"), "close"] == pytest.approx(200.0)

    def test_hourly_gap_detected_and_filled(self) -> None:
        """A missing hour is detected and forward-filled."""
        df = _make_frame(
            ["2026-01-01T09:00:00+00:00", "2026-01-01T11:00:00+00:00"],
            [99.0, 101.0],
        )
        result = prepare_and_fill_data(df, "1h")
        assert Timestamp("2026-01-01T10:00:00") in result.index
        assert result.loc[Timestamp("2026-01-01T10:00:00"), "close"] == pytest.approx(
            99.0
        )

    def test_only_missing_rows_returned(self) -> None:
        """Output contains only the gap rows, not the original present rows."""
        df = _make_frame(
            [
                "2026-01-01T10:00:00+00:00",
                "2026-01-01T10:10:00+00:00",
                "2026-01-01T10:15:00+00:00",
            ],
            [100.0, 101.0, 102.0],
        )
        result = prepare_and_fill_data(df, "5m")
        # Only 10:05 is missing; 10:00, 10:10, 10:15 were present
        assert len(result) == 1
        assert Timestamp("2026-01-01T10:05:00") in result.index
        assert Timestamp("2026-01-01T10:00:00") not in result.index
        assert Timestamp("2026-01-01T10:10:00") not in result.index
