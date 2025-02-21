import math
import re
from typing import Optional

import numpy as np
import pandas as pd

from tastytrade.config.enumerations import Channels
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.providers.market import MarketDataProvider


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
    market_provider: Optional[MarketDataProvider] = None,
    symbol: Optional[str] = None,
    price_col: str = "close",
    length: int = 20,
    displace: int = 0,
    pad_value: Optional[float] = None,
    input_df: Optional[pd.DataFrame] = None,
    dxlink: Optional[DXLinkManager] = None,  # For backwards compatibility
) -> pd.DataFrame:
    """Compute the Hull Moving Average (HMA) for a DataFrame.

    The HMA is defined as:
    HMA = WMA(2 * WMA(price, length/2) - WMA(price, length), sqrt(length))

    Args:
        market_provider: MarketDataProvider instance (new interface)
        symbol: Symbol to compute HMA for (e.g. "SPX{=5m}")
        price_col: Column containing price data. Defaults to "close"
        length: Period for HMA calculation. Defaults to 20
        displace: Number of bars to shift the final HMA. Defaults to 0
        pad_value: Value to pad beginning of series. If None, uses previous day's close
        input_df: Pre-filtered DataFrame to use instead of fetching data
        dxlink: DXLinkManager instance (legacy interface)

    Returns
        DataFrame with HMA values and colors
    """
    if input_df is not None:
        df = input_df.copy()
    elif market_provider is not None and symbol is not None:
        df = market_provider[symbol].to_pandas()
    elif dxlink is not None and symbol is not None:
        df = (
            dxlink.router.handler[Channels.Candle].processors["feed"].frames[symbol].to_pandas()
            if dxlink.router
            else pd.DataFrame()
        )
    else:
        raise ValueError("Must provide either input_df or market_provider/dxlink with symbol")

    if df.empty:
        return pd.DataFrame()

    # Reset index and sort by time to ensure proper calculation
    df = df.sort_values("time").reset_index(drop=True)

    # Get the base symbol for summary lookup
    base_symbol = re.sub(r"\{=\d*\w\}", "", symbol) if symbol else ""

    # Try to get pad value from provider or dxlink
    if pad_value is None:
        try:
            if market_provider is not None:
                # TODO: Implement method to get previous day's close from provider
                pad_value = df[price_col].iloc[0]
            elif dxlink is not None and dxlink.router:
                summary_df = dxlink.router.handler[Channels.Summary].processors["feed"].df
                summary_entry = summary_df["eventSymbol"] == base_symbol
                pad_value = summary_df.loc[summary_entry, "prevDayClosePrice"].iloc[0]
            else:
                pad_value = df[price_col].iloc[0]
        except (IndexError, KeyError, AttributeError):
            pad_value = df[price_col].iloc[0] if not df.empty else None

    if pad_value is None:
        return pd.DataFrame()  # Return empty frame if we can't calculate

    half_length = int(round(length / 2))
    sqrt_length = int(round(math.sqrt(length)))

    # Use the provided pad_value for the entire series
    price = df[price_col]
    wma_half = padded_wma_session(price, half_length, pad_value)
    wma_full = padded_wma_session(price, length, pad_value)
    diff = 2 * wma_half - wma_full
    hma = padded_wma_session(diff, sqrt_length, pad_value)
    if displace:
        hma = hma.shift(-displace)
    df["HMA"] = hma

    # Color assignment: "Up" if current HMA > previous HMA, else "Down"
    df["HMA_color"] = np.where(df["HMA"] > df["HMA"].shift(1), "Up", "Down")

    return df[["time", "HMA", "HMA_color"]]
