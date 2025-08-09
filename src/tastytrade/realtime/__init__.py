"""Realtime streaming components (indicator worker + gateway helpers).

This package contains:
  * schemas: Pydantic models for snapshot & delta wire formats
  * state: Per-symbol incremental indicator state containers
  * worker: Async Redis pub/sub indicator enrichment worker

The worker listens to raw CandleEvent publications emitted by RedisEventProcessor
on channels: ``market:CandleEvent:{eventSymbol}`` and publishes enriched deltas on
``analytics:delta:{eventSymbol}`` while maintaining a snapshot key
``snapshot:{eventSymbol}``.
"""

from .schemas import (
    CandlePayload,
    DeltaMessage,
    HMAPayload,
    MACDPayload,
    Snapshot,
)

__all__ = [
    "DeltaMessage",
    "Snapshot",
    "CandlePayload",
    "MACDPayload",
    "HMAPayload",
]
