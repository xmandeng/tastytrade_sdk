import logging
from collections import defaultdict
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
    symbol: dict[str, pl.DataFrame]

    def process_event(self, event: BaseEvent) -> BaseEvent: ...


class BaseEventProcessor:
    """Base processor that handles DataFrame storage"""

    name: str = "feed"

    def __init__(self) -> None:
        self.pl = pl.DataFrame()
        self.symbol: dict[str, pl.DataFrame] = defaultdict(lambda: pl.DataFrame())

    def process_event(self, event: BaseEvent) -> None:
        self.pl = self.pl.vstack(pl.DataFrame([event]))

        if len(self.pl) > 2 * ROW_LIMIT:
            self.pl = self.pl.tail(ROW_LIMIT)

        # ? Idea: Split into symbol dfs to improve large scale performance
        self.symbol[event.eventSymbol] = self.symbol[event.eventSymbol].vstack(
            pl.DataFrame([event])
        )

        if len(self.symbol[event.eventSymbol]) > 2 * ROW_LIMIT:
            self.symbol[event.eventSymbol] = self.symbol[event.eventSymbol].tail(ROW_LIMIT)

    @property
    def df(self) -> pd.DataFrame:
        return self.pl.to_pandas()

    def last(self, symbol: str) -> pd.DataFrame:
        return self.df.loc[self.df["eventSymbol"] == symbol].tail(1)


class LatestEventProcessor(BaseEventProcessor):
    name = "feed"

    def process_event(self, event: BaseEvent) -> None:

        self.pl = self.pl.vstack(pl.DataFrame([event])).unique(subset=["eventSymbol"], keep="last")


class CandleEventProcessor(BaseEventProcessor):
    """Processor maintains separate dataframes for each symbol, e.g., SPX{=d}, SPX{=5m}, SPX{=15m}, etc.

    Time is always the leading time for each candlestick. This allows for continuous update of unclosed candlesticks
    """

    def __init__(self) -> None:
        self.symbol: dict[str, pl.DataFrame] = defaultdict(lambda: pl.DataFrame())

    def process_event(self, event: CandleEvent) -> None:

        self.symbol[event.eventSymbol] = (
            self.symbol[event.eventSymbol]
            .vstack(pl.DataFrame([event]))
            .unique(subset=["eventSymbol", "time"], keep="last")
            .sort("time", descending=False)
        )

        if len(self.symbol[event.eventSymbol]) > 2 * ROW_LIMIT:
            self.symbol[event.eventSymbol] = self.symbol[event.eventSymbol].tail(ROW_LIMIT)
