import logging
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import polars as pl

from tastytrade.messaging.models.events import BaseEvent, CandleEvent, RawCandleEvent

logger = logging.getLogger(__name__)

ROW_LIMIT = 100_000


# ! EVENT PROCESSORS SHOULD LOG AN ERROR WHEN THEY FAIL TO PROCESS AN EVENT
class EventProcessor(Protocol):
    """Protocol for event processors"""

    name: str
    df: pd.DataFrame

    def process_event(self, event: BaseEvent) -> BaseEvent: ...


class BaseEventProcessor:
    """Base processor that handles DataFrame storage"""

    name = "feed"

    def __init__(self) -> None:
        self.pl = pl.DataFrame()

    def process_event(self, event: BaseEvent) -> BaseEvent:
        self.pl = self.pl.vstack(pl.DataFrame([event]))

        if len(self.pl) > 2 * ROW_LIMIT:
            self.pl = self.pl.tail(ROW_LIMIT)

        return event

    @property
    def df(self) -> pd.DataFrame:
        return self.pl.to_pandas()

    def last(self, symbol: str) -> pd.DataFrame:
        return self.df.loc[self.df["eventSymbol"] == symbol].tail(1)


class CandleEventProcessor(BaseEventProcessor):

    def get_previous_candle(self, event: RawCandleEvent) -> dict[str, Any]:
        candle_df = self.pl.clone()
        if "time" not in candle_df:
            return {}

        candle = (
            candle_df.sort("time", descending=False)
            .filter(pl.col("eventSymbol") == event.eventSymbol)
            .filter(pl.col("time").lt(event.time.replace(tzinfo=None)))
            .tail(1)
        )

        return {} if candle.is_empty() else candle.to_dicts().pop()

    def process_event(self, orig_event: RawCandleEvent) -> CandleEvent:

        previous_candle: dict[str, Any] = self.get_previous_candle(orig_event)

        event: CandleEvent = CandleEvent(
            tradeDate=orig_event.time.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d"),
            tradeTime=orig_event.time.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M"),
            prevOpen=previous_candle.get("open"),
            prevHigh=previous_candle.get("high"),
            prevLow=previous_candle.get("low"),
            prevClose=previous_candle.get("close"),
            prevDate=previous_candle.get("tradeDate"),
            prevTime=previous_candle.get("tradeTime"),
            **orig_event.model_dump(),
        )

        self.pl = (
            self.pl.vstack(pl.DataFrame([event]))
            .unique(subset=["eventSymbol", "time"], keep="last")
            .sort("time", descending=False)
        )

        return event

    @property
    def df(self) -> pd.DataFrame:
        return self.pl.to_pandas().sort_values("time", ascending=True).reset_index(drop=True)


class LatestEventProcessor(BaseEventProcessor):
    name = "feed"

    def process_event(self, event: BaseEvent) -> BaseEvent:

        self.pl = self.pl.vstack(pl.DataFrame([event])).unique(subset=["eventSymbol"], keep="last")

        return event
