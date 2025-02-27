import logging
from collections import namedtuple
from datetime import datetime, time, timedelta
from typing import Optional

import pytz

from tastytrade.providers.market import MarketDataProvider

# Define a namedtuple for the opening range results
OpeningRange = namedtuple("OpeningRange", ["symbol", "range_minutes", "high", "low", "date"])


async def get_opening_range(
    streamer: MarketDataProvider,
    symbol: str,
    range_minutes: int = 5,
    date: Optional[datetime] = None,
    market_open_time: time = time(9, 30),
    timezone: str = "America/New_York",
) -> OpeningRange:
    """
    Calculate the opening range (min low and max high) for a specified symbol.
    Uses the streamer.download() method to fetch the candle data.

    Args:
        streamer: Market data provider instance with download method
        symbol: The event symbol to query (e.g., "SPX{=m}")
        range_minutes: Minutes from market open to include in the opening range (default: 5)
        date: Specific date to query (default: today)
        market_open_time: Market open time (default: 9:30 AM ET)
        timezone: Timezone for market open (default: "America/New_York")

    Returns:
        OpeningRange: A namedtuple containing the symbol, range_minutes, high, low, and date
    """
    logger = logging.getLogger(__name__)

    # Use today if no date is specified
    if date is None:
        date = datetime.now()

    # Ensure date has no time component
    date = datetime(date.year, date.month, date.day)

    # Create market open datetime in the specified timezone
    tz = pytz.timezone(timezone)
    market_open_dt = tz.localize(datetime.combine(date, market_open_time))

    # Calculate range end
    range_end = market_open_dt + timedelta(minutes=range_minutes)

    # Convert to UTC for streamer.download
    market_open_utc = market_open_dt.astimezone(pytz.UTC).replace(tzinfo=None)
    range_end_utc = range_end.astimezone(pytz.UTC).replace(tzinfo=None)

    logger.debug(f"Fetching opening range data for {symbol} with {range_minutes}m range")
    logger.debug(f"Range timeframe: {market_open_utc} to {range_end_utc}")

    try:
        # Use the streamer.download method to get candle data
        candles = streamer.download(
            symbol=symbol,
            start=market_open_utc,
            stop=range_end_utc,
            debug_mode=True,  # Return DataFrame directly instead of storing
        )

        # Check if we have data
        if candles is None or candles.is_empty():
            logger.warning(f"No data found for {symbol} during opening range on {date.date()}")
            return OpeningRange(
                symbol=symbol, range_minutes=range_minutes, high=None, low=None, date=date.date()
            )

        # Calculate the high and low
        try:
            high_value = candles["high"].max()
            low_value = candles["low"].min()

            logger.info(
                f"Opening range for {symbol} ({range_minutes}m): High={high_value}, Low={low_value}"
            )

            return OpeningRange(
                symbol=symbol,
                range_minutes=range_minutes,
                high=high_value,
                low=low_value,
                date=date.date(),
            )
        except Exception as e:
            logger.error(f"Error calculating opening range values: {str(e)}")
            return OpeningRange(
                symbol=symbol, range_minutes=range_minutes, high=None, low=None, date=date.date()
            )

    except Exception as e:
        logger.error(f"Error fetching data for {symbol} opening range: {str(e)}")
        return OpeningRange(
            symbol=symbol, range_minutes=range_minutes, high=None, low=None, date=date.date()
        )
