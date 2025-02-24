import logging
import os
import warnings
from typing import Optional

import pandas as pd
from influxdb_client import InfluxDBClient

from tastytrade.common.logging import setup_logging
from tastytrade.messaging.models.events import CandleEvent
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor
from tastytrade.utils.helpers import format_influx_candle_symbol, parse_candle_symbol

warnings.simplefilter(action="ignore", category=FutureWarning)


logger = logging.getLogger(__name__)

# InfluxDB Connection Details
INFLUX_DB_URL = os.environ.get("INFLUX_DB_URL")
INFLUX_DB_TOKEN = os.environ.get("INFLUX_DB_TOKEN")
INFLUX_DB_ORG = os.environ.get("INFLUX_DB_ORG")
INFLUX_DB_BUCKET = os.environ.get("INFLUX_DB_BUCKET")


def initialize_influx_client() -> InfluxDBClient:
    """Initialize and return an InfluxDB client."""
    return InfluxDBClient(url=INFLUX_DB_URL, token=INFLUX_DB_TOKEN, org=INFLUX_DB_ORG)


def query_candle_event_data(
    client: InfluxDBClient, symbol: str, lookback_days: int
) -> Optional[pd.DataFrame]:
    """Query existing CandleEvent data for the symbol."""
    query_api = client.query_api()

    query = f"""
    from(bucket: "{INFLUX_DB_BUCKET}")
      |> range(start: -{lookback_days}d)
      |> filter(fn: (r) => r["_measurement"] == "CandleEvent")
      |> filter(fn: (r) => r["eventSymbol"] == "{symbol}")
      |> keep(columns: ["_time", "_field", "_value"])
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
    """

    tables = query_api.query_data_frame(query)
    if tables.empty:
        logging.info(
            "No CandleEvent data found for %s in the last %s days",
            symbol,
            str(lookback_days),
        )
        return None

    return tables


def prepare_and_fill_data(tables: pd.DataFrame, time_interval: str) -> pd.DataFrame:
    """Prepare DataFrame, identify missing time buckets using first and last records as bookends, and forward-fill."""
    pandas_interval = time_interval.replace("m", "T").upper()

    # Convert '_time' to datetime and set as index
    tables["_time"] = pd.to_datetime(tables["_time"].dt.tz_localize(None))
    tables.set_index("_time", inplace=True)

    # Use first and last records as bookends
    first_valid_index = tables.index.min()
    last_valid_index = tables.index.max()

    # Create complete time range between bookends
    all_times = pd.date_range(start=first_valid_index, end=last_valid_index, freq=pandas_interval)
    missing_times = all_times[~all_times.isin(tables.index)]

    return tables.reindex(all_times).ffill().loc[missing_times]


def write_candle_events(missing_df: pd.DataFrame, symbol: str):
    """Use TelegrafHTTPEventProcessor to process and write CandleEvent data."""
    processor = TelegrafHTTPEventProcessor()

    logging.info("Processing and writing CandleEvent data via Telegraf for %s", symbol)

    for timestamp, row in missing_df.iterrows():
        try:
            # Populate CandleEvent model directly
            candle_event = CandleEvent(
                time=timestamp,
                eventSymbol=symbol,  # Ensure eventSymbol is passed
                eventFlags=row.get("eventFlags"),
                index=row.get("index"),
                sequence=row.get("sequence"),
                count=row.get("count"),
                open=row.get("open"),
                high=row.get("high"),
                low=row.get("low"),
                close=row.get("close"),
                volume=row.get("volume"),
                bidVolume=row.get("bidVolume"),
                askVolume=row.get("askVolume"),
                openInterest=row.get("openInterest"),
                vwap=row.get("vwap"),
                impVolatility=row.get("impVolatility"),
            )

            # Use Telegraf processor to handle the event
            processor.process_event(candle_event)

        except Exception as e:
            logging.info("[ERROR] Failed to process CandleEvent at %s: %s", timestamp, e)

    # Flush and close the write API to ensure all data is written
    try:
        processor.write_api.flush()
        processor.write_api.close()
        logging.info("Successfully flushed and closed InfluxDB write API")
    except Exception as e:
        logging.info("[ERROR] Failed during flush/close of InfluxDB write API: %s", e)

    logging.info("Forward-fill added %s events for %s", str(len(missing_df)), symbol)


def forward_fill_candle_event(symbol, lookback_days=30):
    """Main function to forward-fill CandleEvent data."""
    client = initialize_influx_client()

    influx_symbol = format_influx_candle_symbol(symbol)
    _, time_interval = parse_candle_symbol(symbol)

    # Removed field_types and allowed_fields since CandleEvent handles validation
    tables = query_candle_event_data(client, influx_symbol, lookback_days)

    if tables is None:
        logging.warning("No data found for %s in the last %s days", symbol, lookback_days)
        client.close()
        return

    gap_fill_df = prepare_and_fill_data(tables, time_interval)

    if gap_fill_df.empty:
        logging.info("No missing data found for %s", symbol)
        client.close()
        return

    # Simplified call without extra parameters
    write_candle_events(gap_fill_df, influx_symbol)

    client.close()


# Example Usage
if __name__ == "__main__":

    setup_logging(
        level=logging.INFO,
        console=True,
    )

    # forward_fill_candle_event(symbol="SPX{=1m}", lookback_days=365 * 25)

    for symbol in ["BTC/USD:CXTALP", "NVDA", "QQQ", "SPY", "SPX"]:
        for interval in ["1d", "1h", "30m", "15m", "5m", "1m"]:
            event_symbol = f"{symbol}{{={interval}}}"
            logging.info("Forward-filling %s", event_symbol)
            forward_fill_candle_event(symbol=event_symbol, lookback_days=365 * 25)
