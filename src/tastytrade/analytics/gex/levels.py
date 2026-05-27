"""Identify GEX concentration levels per expiration.

From the per-(expiration, strike) GEX DataFrame, surface the call wall, put
wall, max-gamma strike, net-gamma wall, and the dominant strikes bracketing
spot. See docs/plans/TT-138-gex-snapshot.md §5.6.
"""

from dataclasses import dataclass
from typing import Optional

import polars as pl


@dataclass(frozen=True)
class Levels:
    """GEX levels for a single expiration (all strikes are in the product's units)."""

    expiration: str
    call_wall: Optional[float]
    put_wall: Optional[float]
    max_abs_gamma: Optional[float]
    net_gamma_wall: Optional[float]
    nearest_above_spot: Optional[float]
    nearest_below_spot: Optional[float]


def identify_levels(strike_df: pl.DataFrame, spot: float) -> list[Levels]:
    """Identify GEX levels for each expiration present in ``strike_df``.

    Args:
        strike_df: Output of ``aggregate_by_strike`` — columns ``expiration``,
            ``strike``, ``call_gex``, ``put_gex``, ``net_gex``, ``abs_gex``.
        spot: Underlying spot price.

    Returns:
        One :class:`Levels` per expiration, ordered by expiration.
    """
    if strike_df.is_empty():
        return []
    return [
        levels_for_expiration(exp, strike_df.filter(pl.col("expiration") == exp), spot)
        for exp in strike_df["expiration"].unique().sort().to_list()
    ]


def levels_for_expiration(expiration: str, sub: pl.DataFrame, spot: float) -> Levels:
    """Compute the levels for one expiration's strike rows."""

    def strike_at(metric: str, *, descending: bool) -> Optional[float]:
        if sub.is_empty():
            return None
        row = sub.sort(metric, descending=descending).head(1)
        return float(row["strike"][0]) if row.height else None

    def nearest_strike(above: bool) -> Optional[float]:
        side = (
            sub.filter(pl.col("strike") > spot).sort("strike")
            if above
            else sub.filter(pl.col("strike") < spot).sort("strike", descending=True)
        )
        return float(side["strike"][0]) if side.height else None

    net_gamma_wall: Optional[float] = None
    if sub.height:
        net_row = (
            sub.with_columns(pl.col("net_gex").abs().alias("abs_net"))
            .sort("abs_net", descending=True)
            .head(1)
        )
        net_gamma_wall = float(net_row["strike"][0]) if net_row.height else None

    return Levels(
        expiration=expiration,
        call_wall=strike_at("call_gex", descending=True),  # most positive call gamma
        put_wall=strike_at("put_gex", descending=False),  # most negative put gamma
        max_abs_gamma=strike_at("abs_gex", descending=True),
        net_gamma_wall=net_gamma_wall,
        nearest_above_spot=nearest_strike(above=True),
        nearest_below_spot=nearest_strike(above=False),
    )
