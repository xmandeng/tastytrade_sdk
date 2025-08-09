from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import polars as pl

from tastytrade.analytics.indicators.momentum import hull as full_hull
from tastytrade.analytics.visualizations.realtime import IncrementalMACDState
from tastytrade.messaging.models.events import CandleEvent

from .schemas import CandlePayload, HMAPayload, MACDPayload


@dataclass
class SymbolIndicatorState:
    symbol: str
    max_rows: int = 1000
    macd_state: Optional[IncrementalMACDState] = None
    df: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())

    def _init_macd(self, first_close: float):
        if self.macd_state is None:
            self.macd_state = IncrementalMACDState(prior_close=first_close)

    def ingest(self, event: CandleEvent):
        if event.close is None:
            return None
        self._init_macd(event.close)
        assert self.macd_state is not None

        row = {
            "time": event.time,
            "open": event.open,
            "high": event.high,
            "low": event.low,
            "close": event.close,
            "volume": event.volume,
        }
        if self.df.is_empty():
            self.df = pl.DataFrame([row])
        else:
            last_time = self.df[-1, "time"]
            if last_time == event.time:
                self.df = self.df.slice(0, len(self.df) - 1).vstack(pl.DataFrame([row]))
            else:
                self.df = self.df.vstack(pl.DataFrame([row]))
        if len(self.df) > self.max_rows:
            self.df = self.df.tail(self.max_rows)

        macd_vals = self.macd_state.update(event.close)
        macd = MACDPayload(
            value=macd_vals["Value"],
            signal=macd_vals["avg"],
            hist=macd_vals["diff"],
            color=macd_vals["diff_color"],
        )

        hma_df = full_hull(self.df.tail(120), pad_value=self.df[0, "close"])  # type: ignore[index]
        if not hma_df.empty:  # pandas DataFrame
            last = hma_df.iloc[-1]
            hma = HMAPayload(value=float(last.HMA), direction=str(last.HMA_color))
        else:
            hma = HMAPayload(value=event.close, direction="Up")

        candle_payload = CandlePayload(
            time=event.time,
            open=event.open or event.close,
            high=event.high or event.close,
            low=event.low or event.close,
            close=event.close,
            volume=event.volume,
        )
        return candle_payload, macd, hma


def build_snapshot(
    symbol: str, candle: CandlePayload, macd: MACDPayload, hma: HMAPayload
):
    from .schemas import Snapshot

    return Snapshot(
        symbol=symbol,
        updated_at=datetime.utcnow(),
        last_candle=candle,
        macd=macd,
        hma=hma,
    )
