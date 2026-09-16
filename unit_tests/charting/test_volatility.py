"""Realized volatility for the IV vs HV pane: window, annualization and the
session-boundary rule."""

import math

import numpy as np
import pytest

from tastytrade.charting.volatility import (
    RealizedVolState,
    VolProfile,
    implied_vol_symbol,
    known_time,
    merge_vol_points,
)

T0 = 1_757_000_000  # any epoch on a five-minute boundary is fine here


def five_minute_state() -> RealizedVolState:
    return RealizedVolState(VolProfile.for_interval("5m"))


class TestVolProfile:
    def test_five_minute_bars_window_is_one_session(self) -> None:
        p = VolProfile.for_interval("5m")
        assert p.window == 78
        assert p.interval_seconds == 300
        assert p.annualization == pytest.approx(math.sqrt(252 * 78))
        assert p.intraday

    def test_one_minute_bars_window_is_one_session(self) -> None:
        assert VolProfile.for_interval("m").window == 390

    def test_hourly_bars_round_the_partial_last_hour_up(self) -> None:
        assert VolProfile.for_interval("1h").window == 7
        assert VolProfile.for_interval("h").window == 7

    def test_daily_bars_use_twenty_sessions(self) -> None:
        p = VolProfile.for_interval("1d")
        assert p.window == 20
        assert p.annualization == pytest.approx(math.sqrt(252))
        assert not p.intraday

    def test_unknown_interval_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            VolProfile.for_interval("2h")


class TestRealizedVol:
    def test_no_estimate_below_two_returns(self) -> None:
        s = five_minute_state()
        assert s.step(100.0, T0) is None
        assert s.step(101.0, T0 + 300) is None
        assert s.step(100.5, T0 + 600) is not None

    def test_matches_sample_std_of_log_returns_annualized(self) -> None:
        closes = [100.0, 100.4, 99.9, 100.7, 100.2, 100.9, 101.3]
        s = five_minute_state()
        value = None
        for i, c in enumerate(closes):
            value = s.step(c, T0 + 300 * i)
        rets = np.diff(np.log(closes))
        expected = float(np.std(rets, ddof=1)) * math.sqrt(252 * 78) * 100
        assert value == pytest.approx(expected, abs=1e-3)

    def test_window_drops_the_oldest_return(self) -> None:
        profile = VolProfile(
            interval_seconds=300, window=3, annualization=1.0, intraday=True
        )
        s = RealizedVolState(profile)
        closes = [100.0, 110.0, 100.0, 100.0, 100.0, 100.0]
        for i, c in enumerate(closes):
            s.step(c, T0 + 300 * i)
        # the big early moves have left the window: the last three returns are all zero
        assert s.value() == 0.0
        assert len(s.returns) == 3

    def test_return_across_a_session_boundary_is_not_taken(self) -> None:
        s = five_minute_state()
        s.step(100.0, T0)
        s.step(100.5, T0 + 300)
        # next morning: an overnight gap, not a bar-to-bar return
        s.step(103.0, T0 + 300 + 17 * 3600)
        assert len(s.returns) == 1
        # trading resumes bar to bar from the new close
        s.step(103.2, T0 + 600 + 17 * 3600)
        assert len(s.returns) == 2
        assert s.returns[-1] == pytest.approx(math.log(103.2 / 103.0))

    def test_daily_bars_take_every_return(self) -> None:
        s = RealizedVolState(VolProfile.for_interval("1d"))
        day = 86400
        s.step(100.0, T0)
        s.step(101.0, T0 + day)
        s.step(102.0, T0 + 3 * day)  # over a weekend
        assert len(s.returns) == 2

    def test_zero_close_is_ignored(self) -> None:
        s = five_minute_state()
        s.step(100.0, T0)
        assert s.step(0.0, T0 + 300) is None
        assert s.last_close == 100.0


class TestSeriesHelpers:
    def test_implied_vol_symbol_follows_the_chart_interval(self) -> None:
        assert implied_vol_symbol("SPX", "5m") == "VIX1D{=5m}"
        assert implied_vol_symbol("SPY", "m") == "VIX1D{=m}"

    def test_no_implied_vol_symbol_for_what_the_index_does_not_describe(self) -> None:
        assert implied_vol_symbol("AAPL", "5m") is None

    def test_merge_keys_points_to_candle_times_only(self) -> None:
        points = merge_vol_points(
            [1, 2, 3], {1: 15.1, 2: 15.2, 9: 99.0}, {2: 11.0, 3: 11.5}
        )
        assert points == [
            {"time": 1, "iv": 15.1, "hv": None},
            {"time": 2, "iv": 15.2, "hv": 11.0},
            {"time": 3, "iv": None, "hv": 11.5},
        ]

    def test_known_time(self) -> None:
        assert known_time([1, 5, 9], 5)
        assert not known_time([1, 5, 9], 6)
        assert not known_time([], 6)
