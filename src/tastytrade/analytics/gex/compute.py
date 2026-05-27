"""Per-option Gamma Exposure (GEX) computation and strike-level aggregation.

GEX formula (TT-138 §5.5): ``gex = OI × γ × M × spot² × 0.01 × sign`` where
``sign`` is ``+1`` for calls and ``-1`` for puts, and ``M`` (the contract
multiplier) is always a **parameter** — never hard-coded. The ``spot² × 0.01``
factor expresses gamma exposure as dollar gamma per 1% move in the underlying.

See docs/plans/TT-138-gex-snapshot.md §4–5.
"""

import logging

import polars as pl

logger = logging.getLogger(__name__)

# spot² × GEX_SCALE → dollar gamma per 1% underlying move.
GEX_SCALE = 0.01


def compute_option_gex(
    df: pl.DataFrame, spot: float, multiplier: float
) -> pl.DataFrame:
    """Compute per-option GEX, returning ``df`` with an added ``gex`` column.

    Args:
        df: Per-option rows. Must contain ``option_type`` (``"C"``/``"P"``),
            ``gamma`` and ``open_interest``; ``strike`` and ``expiration`` are
            carried through for downstream aggregation.
        spot: Underlying spot price.
        multiplier: Contract multiplier (100 for equity-options). Taken as a
            parameter — this function never hard-codes 100.

    Returns:
        ``df`` filtered to rows with both ``gamma`` and ``open_interest``
        present, with a ``gex`` column appended.
    """
    if df.is_empty():
        # Preserve any existing columns at 0 rows; a column-less frame gets a
        # bare gex column (a scalar lit would otherwise broadcast to 1 row).
        if df.width == 0:
            return pl.DataFrame(schema={"gex": pl.Float64})
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias("gex"))

    sign = (
        pl.when(pl.col("option_type") == "C").then(pl.lit(1.0)).otherwise(pl.lit(-1.0))
    )
    out = df.filter(
        pl.col("gamma").is_not_null() & pl.col("open_interest").is_not_null()
    ).with_columns(
        (
            pl.col("open_interest").cast(pl.Float64)
            * pl.col("gamma").cast(pl.Float64)
            * multiplier
            * (spot**2)
            * GEX_SCALE
            * sign
        ).alias("gex")
    )
    logger.debug(
        "Computed GEX for %d/%d options (spot=%.2f, M=%g)",
        out.height,
        df.height,
        spot,
        multiplier,
    )
    return out


def aggregate_by_strike(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate per-option GEX into one row per ``(expiration, strike)``.

    Args:
        df: Output of :func:`compute_option_gex` (must contain ``gex``).

    Returns:
        Columns ``expiration``, ``strike``, ``call_gex``, ``put_gex``,
        ``net_gex`` (= call + put), ``abs_gex`` (= |call| + |put|), sorted by
        ``(expiration, strike)``.
    """
    empty_schema = {
        "expiration": pl.Utf8,
        "strike": pl.Float64,
        "call_gex": pl.Float64,
        "put_gex": pl.Float64,
        "net_gex": pl.Float64,
        "abs_gex": pl.Float64,
    }
    if df.is_empty() or "gex" not in df.columns:
        return pl.DataFrame(schema=empty_schema)

    return (
        df.group_by(["expiration", "strike"])
        .agg(
            pl.col("gex").filter(pl.col("option_type") == "C").sum().alias("call_gex"),
            pl.col("gex").filter(pl.col("option_type") == "P").sum().alias("put_gex"),
        )
        .with_columns(
            pl.col("call_gex").fill_null(0.0),
            pl.col("put_gex").fill_null(0.0),
        )
        .with_columns(
            (pl.col("call_gex") + pl.col("put_gex")).alias("net_gex"),
            (pl.col("call_gex").abs() + pl.col("put_gex").abs()).alias("abs_gex"),
        )
        .sort(["expiration", "strike"])
    )
