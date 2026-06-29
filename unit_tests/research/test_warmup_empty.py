"""Warmup must not crash the collector when the history window is empty.

A Monday whose warmup window falls on the weekend (or an InfluxDB gap) returns
an empty frame; warmup is an optimization, so it should degrade to a cold engine
instead of raising and killing the whole day's collection (regression: Jun 29
2026, polars ColumnNotFoundError on df.sort("time") of an empty frame).
"""

from datetime import date

import polars as pl
import pytest

from research.tt156_zero_dte_butterfly import signals
from research.tt156_zero_dte_butterfly.signals import LiveSignalEngine


class FakeEngine:
    def __init__(self) -> None:
        self.candles: list[object] = []
        self._states: dict[str, object] = {}

    def set_prior_close(self, symbol: str, value: float) -> None:
        pass

    def on_candle_event(self, event: object) -> None:
        self.candles.append(event)


class FakeInflux:
    def close(self) -> None:
        pass


class FakePriorCandle:
    close = None


class FakeProvider:
    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame

    def get_daily_candle(self, symbol: str, day: date) -> FakePriorCandle:
        return FakePriorCandle()

    def download(self, symbol: str, start: date, stop: date) -> pl.DataFrame:
        return self.frame


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(signals, "initialize_influx_client", lambda: FakeInflux())
    monkeypatch.setattr(signals, "RedisConfigManager", lambda: object())
    monkeypatch.setattr(signals, "RedisSubscription", lambda config: object())


def test_empty_warmup_frame_does_not_raise(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        signals, "MarketDataProvider", lambda **kw: FakeProvider(pl.DataFrame())
    )
    eng = LiveSignalEngine(confirm_on_close=True)
    fake = FakeEngine()
    eng.engine = fake  # type: ignore[assignment]

    eng.warmup(date(2026, 6, 29))  # must not raise

    assert fake.candles == []  # cold start — no history replayed


def test_populated_warmup_frame_replays(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A non-empty frame with a "time" column still replays normally.
    frame = pl.DataFrame({"time": [], "eventSymbol": [], "close": []})
    monkeypatch.setattr(signals, "MarketDataProvider", lambda **kw: FakeProvider(frame))
    eng = LiveSignalEngine(confirm_on_close=True)
    fake = FakeEngine()
    eng.engine = fake  # type: ignore[assignment]

    eng.warmup(date(2026, 6, 29))  # has the column → takes the replay path, no raise
