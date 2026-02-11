import logging
import math

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


def padded_wma(values: np.ndarray, period: int, pad_value: float) -> np.ndarray:
    """Compute a weighted moving average (WMA) over a fixed window by padding the beginning with a given pad_value.

    This mimics the ThinkOrSwim behavior of seeding the calculation with a prior value.

    For each index i (0-indexed):
       - If i+1 < period, the window becomes:
             [pad_value]*(period - (i+1)) concatenated with values[0:i+1]
       - Otherwise, the window is the usual last ``period`` observations.

    Weights are 1, 2, …, period.

    Args:
        values: Input array of price data.
        period: Window size for moving average calculation.
        pad_value: Value used to pad the beginning of the series.

    Returns:
        Array containing weighted moving average values.
    """
    weights = np.arange(1, period + 1)
    weight_sum = weights.sum()
    result = np.empty(len(values))
    for i in range(len(values)):
        if (i + 1) < period:
            pad_count = period - (i + 1)
            window = np.concatenate((np.full(pad_count, pad_value), values[: i + 1]))
        else:
            window = values[i - period + 1 : i + 1]
        result[i] = np.dot(window, weights) / weight_sum
    return result


def hull(
    input_df: pl.DataFrame,
    price_col: str = "close",
    length: int = 20,
    displace: int = 0,
    pad_value: float | None = None,
) -> pl.DataFrame:
    """Compute the Hull Moving Average (HMA) for a DataFrame.

    The HMA is defined as:
    HMA = WMA(2 * WMA(price, length/2) - WMA(price, length), sqrt(length))

    Args:
        input_df: Polars DataFrame containing OHLC data.
        price_col: Name of the column containing price data.
        length: Period for HMA calculation.
        displace: Number of bars to shift the final HMA.
        pad_value: Value to pad beginning of series. If None, uses first close.

    Returns:
        Polars DataFrame with columns: time, HMA, HMA_color.
    """
    if input_df.height == 0:
        logger.warning("Can't calculate Hull Moving Average: Input DataFrame is empty")
        return pl.DataFrame()

    close_values = input_df[price_col].to_numpy().astype(float)

    if pad_value is None:
        pad_value = float(close_values[0])

    half_length = int(round(length / 2))
    sqrt_length = int(round(math.sqrt(length)))

    wma_half = padded_wma(close_values, half_length, pad_value)
    wma_full = padded_wma(close_values, length, pad_value)
    diff = 2 * wma_half - wma_full
    hma = padded_wma(diff, sqrt_length, pad_value)

    if displace:
        hma = np.roll(hma, -displace)
        hma[-displace:] = np.nan

    # Color assignment: "Up" if current HMA > previous HMA, else "Down"
    hma_prev = np.empty_like(hma)
    hma_prev[0] = np.nan
    hma_prev[1:] = hma[:-1]
    hma_color = np.where(hma > hma_prev, "Up", "Down")

    return pl.DataFrame(
        {
            "time": input_df["time"],
            "HMA": hma,
            "HMA_color": hma_color,
        }
    )


def ema_with_seed(values: np.ndarray, length: int, seed: float) -> np.ndarray:
    alpha = 2.0 / (length + 1.0)
    out = np.zeros_like(values, dtype=float)
    if len(values) == 0:
        return out

    # Seed the first EMA
    out[0] = alpha * values[0] + (1 - alpha) * seed
    # Compute forward
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]

    return out


def macd(
    df: pl.DataFrame,
    prior_close: float | None,
    fast_length: int = 12,
    slow_length: int = 26,
    macd_length: int = 9,
) -> pl.DataFrame:
    """Compute MACD with EMA seeding.

    Args:
        df: Polars DataFrame containing a 'close' column.
        prior_close: Previous session close used to seed the EMAs. If None, falls back to
            the first non-null close in df.
        fast_length: Fast EMA period.
        slow_length: Slow EMA period.
        macd_length: Signal EMA period.
    """
    # Sort by time just to be safe
    df = df.sort("time")

    # Resolve prior_close if missing
    if prior_close is None:
        try:
            first_close_series = df.select(pl.col("close").drop_nulls()).to_series()
            if len(first_close_series) == 0:
                raise ValueError("Cannot infer prior_close: no non-null close values")
            prior_close = float(first_close_series[0])
        except Exception as e:  # pragma: no cover - defensive
            raise ValueError("prior_close is required and could not be inferred") from e

    # Convert 'close' to numpy
    close_np = df["close"].to_numpy()

    # 1) Fast EMA (seeded by prior_close)
    ema_fast = ema_with_seed(close_np, fast_length, seed=prior_close)
    # 2) Slow EMA (seeded by prior_close)
    ema_slow = ema_with_seed(close_np, slow_length, seed=prior_close)
    # MACD Value line
    value = ema_fast - ema_slow

    # 3) Signal line = EMA of Value (seed with 0.0 or some small guess).
    #    If you prefer to seed it with prior day's final MACD, you can do so;
    #    but the simplest is to seed with 0.0 or the difference from prior_close.
    signal_seed = 0.0
    ema_signal = ema_with_seed(value, macd_length, seed=signal_seed)

    # 4) Histogram
    diff = value - ema_signal
    # Calculate diff colors based on value and previous value
    diff_colors = np.empty(len(diff), dtype=object)

    for i in range(len(diff)):
        if i == 0:  # First value
            if diff[i] > 0:
                diff_colors[i] = "#04FE00"  # Bright green for first positive
            else:
                diff_colors[i] = "#FE0000"  # Bright red for first negative
        else:  # All other values
            if diff[i] > 0:  # Positive values
                if diff[i] > diff[i - 1]:
                    diff_colors[i] = "#04FE00"  # Bright green for increasing positive
                else:
                    diff_colors[i] = "#006401"  # Dark green for decreasing positive
            else:  # Negative values
                if diff[i] < diff[i - 1]:
                    diff_colors[i] = "#FE0000"  # Bright red for decreasing negative
                else:
                    diff_colors[i] = "#7E0100"  # Dark red for increasing negative
    # Attach them as new columns
    df_res = df.with_columns(
        [
            pl.Series("Value", value),
            pl.Series("avg", ema_signal),
            pl.Series("diff", diff),
            pl.Series("diff_color", diff_colors),
        ]
    )
    return df_res
