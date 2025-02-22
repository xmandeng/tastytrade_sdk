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
