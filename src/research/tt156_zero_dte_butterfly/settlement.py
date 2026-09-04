"""Settlement price: the official SPX close, and nothing else.

SPXW PM-settled options settle to the official SPX closing value. The
index keeps updating for several minutes after 16:00 ET as late prints
arrive, so a snapshot spot taken at or before 16:00 is never that value;
an audit of 56 sessions found a median miss of 1.5 points and one of
15.6. The official close is the close of the SPX daily candle in InfluxDB
for the session date, final by about 16:05 ET.

There is no fallback. If the candle for the session date is missing, or
the session has not closed yet, the caller gets ``None`` and must leave
its structures unsettled.
"""

import logging
from datetime import date, datetime, time
from typing import Protocol

from research.tt156_zero_dte_butterfly.config import ET

logger = logging.getLogger(__name__)

SYMBOL = "SPX"
# The index's final close has been published by 16:05 on every session
# audited; before that the daily candle still carries a running value.
CLOSE_FINAL = time(16, 5)


class DailyCandleSource(Protocol):
    def get_daily_candle(self, symbol: str, target_date: date) -> object: ...


def official_close(
    source: DailyCandleSource, day: date, now: datetime | None = None
) -> float | None:
    """Official SPX close for ``day`` or ``None`` when it is not final yet.

    ``get_daily_candle`` walks back to earlier trading days when the target
    date has no candle; that is exactly the substitution a settlement must
    never make, so the candle's own date is checked against ``day``.
    """
    now = now or datetime.now(ET)
    now_et = now.astimezone(ET)
    if day == now_et.date() and now_et.time() < CLOSE_FINAL:
        logger.error(
            "Official close for %s is not final before %s ET", day, CLOSE_FINAL
        )
        return None
    try:
        candle = source.get_daily_candle(SYMBOL, day)
    except ValueError:
        logger.error("No SPX daily candle for %s", day)
        return None
    candle_time = getattr(candle, "time", None)
    close = getattr(candle, "close", None)
    if candle_time is None or candle_time.date() != day or close is None:
        logger.error(
            "SPX daily candle for %s came back dated %s; refusing to settle",
            day,
            candle_time,
        )
        return None
    return float(close)


def influx_source() -> tuple[DailyCandleSource, object]:
    from tastytrade.config import RedisConfigManager
    from tastytrade.providers.market import MarketDataProvider
    from tastytrade.providers.subscriptions import RedisSubscription
    from tastytrade.utils.time_series import initialize_influx_client

    influx = initialize_influx_client()
    provider = MarketDataProvider(
        data_feed=RedisSubscription(RedisConfigManager()), influx=influx
    )
    return provider, influx
