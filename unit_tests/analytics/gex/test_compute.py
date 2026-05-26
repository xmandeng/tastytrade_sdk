"""Unit tests for GEX per-option computation and strike aggregation (TT-139)."""

import polars as pl
import pytest

from tastytrade.analytics.gex.compute import aggregate_by_strike, compute_option_gex


def one_option(
    option_type: str, gamma, open_interest, strike=100.0, expiration="2026-05-19"
):
    return pl.DataFrame(
        {
            "option_type": [option_type],
            "gamma": [gamma],
            "open_interest": [open_interest],
            "strike": [strike],
            "expiration": [expiration],
        }
    )


def test_call_gex_sign_positive():
    out = compute_option_gex(one_option("C", 0.01, 100.0), spot=100.0, multiplier=100.0)
    assert out.height == 1
    assert out["gex"][0] > 0


def test_put_gex_sign_negative():
    out = compute_option_gex(one_option("P", 0.01, 100.0), spot=100.0, multiplier=100.0)
    assert out["gex"][0] < 0


def test_zero_open_interest_yields_zero_gex():
    out = compute_option_gex(one_option("C", 0.01, 0.0), spot=100.0, multiplier=100.0)
    assert out["gex"][0] == 0.0


def test_missing_gamma_is_excluded():
    out = compute_option_gex(one_option("C", None, 100.0), spot=100.0, multiplier=100.0)
    assert out.height == 0


def test_missing_open_interest_is_excluded():
    out = compute_option_gex(one_option("C", 0.01, None), spot=100.0, multiplier=100.0)
    assert out.height == 0


@pytest.mark.parametrize("multiplier", [100.0, 50.0, 5.0])
def test_gex_scales_linearly_with_multiplier(multiplier):
    base = compute_option_gex(one_option("C", 0.01, 100.0), spot=100.0, multiplier=1.0)
    scaled = compute_option_gex(
        one_option("C", 0.01, 100.0), spot=100.0, multiplier=multiplier
    )
    assert scaled["gex"][0] == pytest.approx(base["gex"][0] * multiplier)


def test_formula_value():
    # gex = OI(100) * gamma(0.01) * M(100) * spot^2(100^2) * 0.01 * sign(+1)
    out = compute_option_gex(one_option("C", 0.01, 100.0), spot=100.0, multiplier=100.0)
    assert out["gex"][0] == pytest.approx(100 * 0.01 * 100 * (100**2) * 0.01)


def test_empty_input_returns_empty_with_gex_column():
    out = compute_option_gex(pl.DataFrame(), spot=100.0, multiplier=100.0)
    assert "gex" in out.columns
    assert out.height == 0


def test_aggregate_by_strike_sums_per_strike():
    df = pl.DataFrame(
        {
            "option_type": ["C", "C", "P"],
            "gamma": [0.01, 0.01, 0.02],
            "open_interest": [100.0, 50.0, 100.0],
            "strike": [100.0, 100.0, 100.0],
            "expiration": ["2026-05-19"] * 3,
        }
    )
    priced = compute_option_gex(df, spot=100.0, multiplier=100.0)
    agg = aggregate_by_strike(priced)
    assert agg.height == 1
    row = agg.row(0, named=True)
    # Two calls (OI 100 + 50) summed; one put (negative).
    assert row["call_gex"] > 0
    assert row["put_gex"] < 0
    assert row["net_gex"] == pytest.approx(row["call_gex"] + row["put_gex"])
    assert row["abs_gex"] == pytest.approx(abs(row["call_gex"]) + abs(row["put_gex"]))


def test_aggregate_groups_by_expiration_and_strike():
    df = pl.DataFrame(
        {
            "option_type": ["C", "C"],
            "gamma": [0.01, 0.01],
            "open_interest": [100.0, 100.0],
            "strike": [100.0, 105.0],
            "expiration": ["2026-05-19", "2026-05-20"],
        }
    )
    agg = aggregate_by_strike(compute_option_gex(df, spot=100.0, multiplier=100.0))
    assert agg.height == 2
    assert set(agg["expiration"].to_list()) == {"2026-05-19", "2026-05-20"}


def test_aggregate_empty_returns_typed_empty():
    agg = aggregate_by_strike(pl.DataFrame())
    assert agg.height == 0
    assert set(agg.columns) == {
        "expiration",
        "strike",
        "call_gex",
        "put_gex",
        "net_gex",
        "abs_gex",
    }
