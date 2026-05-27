"""Unit tests for GEX level identification (TT-139)."""

import polars as pl

from tastytrade.analytics.gex.levels import Levels, identify_levels


def strikes_df():
    # Hand-built per-(expiration, strike) GEX rows for one expiration.
    return pl.DataFrame(
        {
            "expiration": ["2026-05-19"] * 4,
            "strike": [95.0, 100.0, 105.0, 110.0],
            "call_gex": [10.0, 40.0, 80.0, 5.0],
            "put_gex": [-60.0, -90.0, -10.0, -2.0],
            "net_gex": [-50.0, -50.0, 70.0, 3.0],
            "abs_gex": [70.0, 130.0, 90.0, 7.0],
        }
    )


def test_call_wall_is_max_call_gex_strike():
    levels = identify_levels(strikes_df(), spot=101.0)[0]
    assert levels.call_wall == 105.0  # call_gex peaks at 105


def test_put_wall_is_most_negative_put_gex_strike():
    levels = identify_levels(strikes_df(), spot=101.0)[0]
    assert levels.put_wall == 100.0  # put_gex most negative at 100


def test_max_abs_gamma_strike():
    levels = identify_levels(strikes_df(), spot=101.0)[0]
    assert levels.max_abs_gamma == 100.0  # abs_gex peaks at 100 (130)


def test_net_gamma_wall_is_largest_abs_net():
    levels = identify_levels(strikes_df(), spot=101.0)[0]
    assert levels.net_gamma_wall == 105.0  # |net_gex| largest at 105 (70)


def test_nearest_strikes_bracket_spot():
    levels = identify_levels(strikes_df(), spot=101.0)[0]
    assert levels.nearest_above_spot == 105.0
    assert levels.nearest_below_spot == 100.0


def test_empty_returns_no_levels():
    assert identify_levels(pl.DataFrame(), spot=100.0) == []


def test_one_levels_object_per_expiration():
    df = pl.DataFrame(
        {
            "expiration": ["2026-05-19", "2026-05-20"],
            "strike": [100.0, 100.0],
            "call_gex": [10.0, 20.0],
            "put_gex": [-5.0, -5.0],
            "net_gex": [5.0, 15.0],
            "abs_gex": [15.0, 25.0],
        }
    )
    levels = identify_levels(df, spot=100.0)
    assert len(levels) == 2
    assert all(isinstance(level, Levels) for level in levels)
    assert [level.expiration for level in levels] == ["2026-05-19", "2026-05-20"]


def test_nearest_below_none_when_all_strikes_above_spot():
    df = pl.DataFrame(
        {
            "expiration": ["2026-05-19", "2026-05-19"],
            "strike": [110.0, 120.0],
            "call_gex": [10.0, 20.0],
            "put_gex": [-5.0, -5.0],
            "net_gex": [5.0, 15.0],
            "abs_gex": [15.0, 25.0],
        }
    )
    levels = identify_levels(df, spot=100.0)[0]
    assert levels.nearest_below_spot is None
    assert levels.nearest_above_spot == 110.0
