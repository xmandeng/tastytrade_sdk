import logging
from typing import Protocol

import pandas as pd
import polars as pl

from tastytrade.messaging.models.events import BaseEvent, CandleEvent

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

    def process_event(self, event: BaseEvent) -> None:
        self.pl = self.pl.vstack(pl.DataFrame([event]))

        if len(self.pl) > 2 * ROW_LIMIT:
            self.pl = self.pl.tail(ROW_LIMIT)

    @property
    def df(self) -> pd.DataFrame:
        return self.pl.to_pandas()

    def last(self, symbol: str) -> pd.DataFrame:
        return self.df.loc[self.df["eventSymbol"] == symbol].tail(1)


class CandleEventProcessor(BaseEventProcessor):

    def process_event(self, event: CandleEvent) -> None:

        self.pl = (
            self.pl.vstack(pl.DataFrame([event]))
            .unique(subset=["eventSymbol", "time"], keep="last")
            .sort("time", descending=False)
        )

    @property
    def df(self) -> pd.DataFrame:
        return self.pl.to_pandas().sort_values("time", ascending=True).reset_index(drop=True)


class LatestEventProcessor(BaseEventProcessor):
    name = "feed"

    def process_event(self, event: BaseEvent) -> None:

        self.pl = self.pl.vstack(pl.DataFrame([event])).unique(subset=["eventSymbol"], keep="last")
