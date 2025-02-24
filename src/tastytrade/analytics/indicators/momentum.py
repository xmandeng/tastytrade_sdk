import logging
import math

import numpy as np
import pandas as pd
import polars as pl

logger = logging.getLogger(__name__)


def padded_wma_series(series, period, pad_value):
    """Compute a weighted moving average (WMA) on a Series over a fixed window (period) by padding the beginning of the Series with a given pad_value.

    This mimics the ThinkOrSwim behavior of seeding the calculation with a prior value.

    For each index i (0-indexed):
       - If i+1 < period, the window becomes:
             [pad_value]*(period - (i+1)) concatenated with series.iloc[0:i+1]
       - Otherwise, the window is the usual last `period` observations.

    Weights are 1, 2, …, period.

    Args:
        series (pd.Series): Input time series data
        period (int): Window size for moving average calculation
        pad_value (float): Value used to pad the beginning of the series

    Returns
        pd.Series: Series containing weighted moving average values with same index as input

    """
    weights = np.arange(1, period + 1)
    weight_sum = weights.sum()
    result = []
    vals = series.values
    for i in range(len(vals)):
        if (i + 1) < period:
            pad_count = period - (i + 1)
            window = np.concatenate((np.full(pad_count, pad_value), vals[: i + 1]))
        else:
            window = vals[i - period + 1 : i + 1]
        result.append(np.dot(window, weights) / weight_sum)
    return pd.Series(result, index=series.index)


def hull(
    input_df: pl.DataFrame,
    price_col="close",
    length=20,
    displace=0,
    pad_value=None,
):
    """Compute the Hull Moving Average (HMA) for a DataFrame.

    The HMA is defined as:
    HMA = WMA(2 * WMA(price, length/2) - WMA(price, length), sqrt(length))

    Args:
        dxlink (DXLinkManager): DXLink manager instance for data access
        symbol (str): Symbol to compute HMA for (e.g. "SPX{=5m}")
        price_col (str, optional): Name of the column containing price data. Defaults to "close".
        length (int, optional): Period for HMA calculation. Defaults to 20.
        displace (int, optional): Number of bars to shift the final HMA. Defaults to 0.
        pad_value (float, optional): Value to pad beginning of series. If None, uses previous day's close. Defaults to None.
        input_df (pd.DataFrame, optional): Pre-filtered DataFrame to use instead of fetching data. Defaults to None.

    Returns
        pd.DataFrame: DataFrame with added columns:
            - HMA: Hull Moving Average values
            - HMA_color: "Up" when current HMA > previous HMA, "Down" otherwise
    """
    df = input_df.to_pandas().copy()

    if df.empty:
        logger.warning("Can't calculate Hull Moving Average: Input DataFrame is empty")
        return pd.DataFrame()

    if pad_value is None:
        pad_value = df[price_col].iloc[0]

    half_length = int(round(length / 2))
    sqrt_length = int(round(math.sqrt(length)))

    # Use the provided pad_value for the entire series
    price = df[price_col]
    wma_half = padded_wma_series(price, half_length, pad_value)
    wma_full = padded_wma_series(price, length, pad_value)
    diff = 2 * wma_half - wma_full
    hma = padded_wma_series(diff, sqrt_length, pad_value)

    if displace:
        hma = hma.shift(-displace)
    df["HMA"] = hma

    # Color assignment: "Up" if current HMA > previous HMA, else "Down"
    df["HMA_color"] = np.where(df["HMA"] > df["HMA"].shift(1), "Up", "Down")

    return df[["time", "HMA", "HMA_color"]]


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
    prior_close: float,
    fast_length: int = 12,
    slow_length: int = 26,
    macd_length: int = 9,
) -> pl.DataFrame:
    # Sort by time just to be safe
    df = df.sort("time")

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
