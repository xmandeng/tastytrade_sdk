"""Volatility series for the chart's IV vs HV pane.

Implied volatility is Cboe's one-day SPX expected-volatility index (VIX1D),
which DXLink carries as an ordinary candle symbol, so it arrives through
the same history and live paths as every other candle. Realized volatility
is computed here from the charted symbol's own closes, tenor-matched to
that one-day horizon: a trailing window of one regular session of bars.
"""

import math
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from typing import Any

IMPLIED_VOL_SYMBOL = "VIX1D"
# VIX1D is built from SPX options, so it describes the index and what
# tracks it; on any other chart the pane shows realized vol alone.
IMPLIED_VOL_UNDERLYINGS = frozenset({"SPX", "SPXW", "SPY"})

RTH_MINUTES = 390
SESSIONS_PER_YEAR = 252
DAILY_WINDOW_SESSIONS = 20

INTERVAL_SECONDS = {
    "m": 60,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "h": 3600,
    "1h": 3600,
    "d": 86400,
    "1d": 86400,
}


@dataclass(frozen=True)
class VolProfile:
    """How closes at one candle interval turn into an annualized vol."""

    interval_seconds: int
    window: int
    annualization: float
    intraday: bool

    @classmethod
    def for_interval(cls, interval: str) -> "VolProfile":
        seconds = INTERVAL_SECONDS.get(interval)
        if seconds is None:
            raise ValueError(f"Unknown candle interval: {interval}")
        if seconds >= 86400:
            return cls(
                interval_seconds=seconds,
                window=DAILY_WINDOW_SESSIONS,
                annualization=math.sqrt(SESSIONS_PER_YEAR),
                intraday=False,
            )
        bars_per_session = math.ceil(RTH_MINUTES * 60 / seconds)
        return cls(
            interval_seconds=seconds,
            window=bars_per_session,
            annualization=math.sqrt(SESSIONS_PER_YEAR * bars_per_session),
            intraday=True,
        )


@dataclass
class RealizedVolState:
    """Trailing realized volatility of candle closes, in vol points.

    A log return is taken only between consecutive bars: intraday, that
    means bars exactly one interval apart, so the overnight gap never
    enters a session-horizon measure. Below two returns there is no
    estimate and ``step`` returns None.
    """

    profile: VolProfile
    returns: deque[float] = field(default_factory=deque)
    last_close: float | None = None
    last_epoch: int | None = None

    def step(self, close: float, epoch: int) -> float | None:
        if close <= 0:
            return self.value()
        if self.last_close is not None and self.last_epoch is not None:
            consecutive = (
                not self.profile.intraday
                or epoch - self.last_epoch == self.profile.interval_seconds
            )
            if consecutive:
                self.returns.append(math.log(close / self.last_close))
                while len(self.returns) > self.profile.window:
                    self.returns.popleft()
        self.last_close, self.last_epoch = close, epoch
        return self.value()

    def value(self) -> float | None:
        n = len(self.returns)
        if n < 2:
            return None
        mean = sum(self.returns) / n
        var = sum((r - mean) ** 2 for r in self.returns) / (n - 1)
        return round(math.sqrt(var) * self.profile.annualization * 100.0, 3)


def implied_vol_symbol(symbol: str, interval: str) -> str | None:
    """The implied-vol index's candle symbol for a chart, or None when the
    index does not describe the charted symbol."""
    if symbol not in IMPLIED_VOL_UNDERLYINGS:
        return None
    return f"{IMPLIED_VOL_SYMBOL}{{={interval}}}"


def merge_vol_points(
    candle_epochs: list[int],
    implied: dict[int, float],
    realized: dict[int, float | None],
) -> list[dict[str, Any]]:
    """One point per candle time carrying whichever series has a value.

    Points are keyed to the candle pane's own times so the lower pane
    never adds time slots the candles lack. A missing value is null and
    draws as a gap.
    """
    return [
        {"time": t, "iv": implied.get(t), "hv": realized.get(t)} for t in candle_epochs
    ]


def known_time(candle_epochs: list[int], epoch: int) -> bool:
    idx = bisect_right(candle_epochs, epoch)
    return idx > 0 and candle_epochs[idx - 1] == epoch
