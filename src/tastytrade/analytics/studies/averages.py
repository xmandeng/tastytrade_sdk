import math
import re

import numpy as np
import pandas as pd

from tastytrade.sessions.enumerations import Channels
from tastytrade.sessions.sockets import DXLinkManager


def padded_wma_session(series, period, pad_value):
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
    dxlink: DXLinkManager, symbol: str, price_col="close", length=20, displace=0, pad_value=None
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

    Returns
        pd.DataFrame: DataFrame with added columns:
            - HMA: Hull Moving Average values
            - HMA_color: "Up" when current HMA > previous HMA, "Down" otherwise
    """
    df = (
        dxlink.router.handler[Channels.Candle]
        .processors["feed"]
        .df.loc[lambda x: x["eventSymbol"] == symbol]
    )

    # Convert timestamps to EDT and then remove timezone info
    df["time"] = (
        df["time"]
        .dt.tz_localize("UTC")
        .dt.tz_convert("America/New_York")
        .dt.tz_localize(None)  # Remove timezone info
    )

    summary_df = dxlink.router.handler[Channels.Summary].processors["feed"].df
    summary_entry = summary_df["eventSymbol"] == re.sub(r"\{=\d*\w\}", "", symbol)
    pad_value = summary_df.loc[summary_entry, "prevDayClosePrice"].iloc[0]

    half_length = int(round(length / 2))
    sqrt_length = int(round(math.sqrt(length)))

    if pad_value is not None:
        # Use the provided pad_value for the entire series (treat all data as one session)
        price = df[price_col]
        wma_half = padded_wma_session(price, half_length, pad_value)
        wma_full = padded_wma_session(price, length, pad_value)
        diff = 2 * wma_half - wma_full
        hma = padded_wma_session(diff, sqrt_length, pad_value)
        if displace:
            hma = hma.shift(-displace)
        df["HMA"] = hma
    else:
        # Group the data by day and use the previous day's close as the pad value.
        df = (
            dxlink.router.handler[Channels.Candle]
            .processors["feed"]
            .df.loc[lambda x: x["eventSymbol"] == "SPX{=5m}"]
        )

        df["session"] = df.index.date  # temporary grouping by date
        hma_all = pd.Series(index=df.index, dtype=float)
        previous_close = None
        for session, group in df.groupby("session", sort=True):
            # For the first session, if no previous close exists, use the first bar's price.
            current_pad = group[price_col].iloc[0] if previous_close is None else previous_close
            session_price = group[price_col]
            wma_half = padded_wma_session(session_price, half_length, current_pad)
            wma_full = padded_wma_session(session_price, length, current_pad)
            diff = 2 * wma_half - wma_full
            hma_session = padded_wma_session(diff, sqrt_length, current_pad)
            if displace:
                hma_session = hma_session.shift(-displace)
            hma_all.loc[group.index] = hma_session
            previous_close = group[price_col].iloc[-1]
        df["HMA"] = hma_all
        df.drop(columns=["session"], inplace=True)

    # Color assignment: "Up" if current HMA > previous HMA, else "Down"
    df["HMA_color"] = np.where(df["HMA"] > df["HMA"].shift(1), "Up", "Down")

    return df[["time", "HMA", "HMA_color"]]
