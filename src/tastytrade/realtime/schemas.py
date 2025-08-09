from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CandlePayload(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


class MACDPayload(BaseModel):
    value: float = Field(description="MACD value (fast - slow)")
    signal: float = Field(description="Signal line (EMA of value)")
    hist: float = Field(description="Histogram (value - signal)")
    color: str = Field(description="Color code for histogram bar")


class HMAPayload(BaseModel):
    value: float
    direction: Literal["Up", "Down"]


class DeltaMessage(BaseModel):
    type: Literal["delta"] = "delta"
    symbol: str
    candle: CandlePayload
    macd: MACDPayload
    hma: HMAPayload


class Snapshot(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    symbol: str
    updated_at: datetime
    last_candle: CandlePayload
    macd: MACDPayload
    hma: HMAPayload
