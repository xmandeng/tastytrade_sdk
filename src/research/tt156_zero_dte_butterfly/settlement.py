"""Settlement price: the official SPX close, and nothing else.

SPXW PM-settled options settle to the official SPX closing value. The
index keeps updating for several minutes after 16:00 ET as late prints
arrive, so a snapshot spot taken at or before 16:00 is never that value;
an audit of 56 sessions found a median miss of 1.5 points and one of
15.6. The official close is the close of the SPX daily candle in InfluxDB
for the session date, final by about 16:05 ET.

Two readers of the same feed value, per the project's data-source rule
(live values from Redis, history from InfluxDB):

* ``live_official_close`` reads the SPX daily candle from the Redis
  latest-event hash. This is what the collector settles from at 16:15.
  InfluxDB cannot serve that read: since the sealed-bar write change the
  daily candle is written only when the next session's bar begins.
* ``official_close`` reads the InfluxDB daily candle for a past session,
  for restatement and audits.

There is no fallback in either. If the candle for the session date is
missing, or the session has not closed yet, the caller gets ``None`` and
must leave its structures unsettled.
"""

import json
import logging
from datetime import date, datetime, time
from typing import Protocol

from research.tt156_zero_dte_butterfly.config import ET
from tastytrade.messaging.models.events import CandleEvent

logger = logging.getLogger(__name__)

SYMBOL = "SPX"
DAILY_SYMBOL = "SPX{=d}"
LATEST_CANDLES_KEY = "tastytrade:latest:CandleEvent"
# The index's final close has been published by 16:05 on every session
# audited; before that the daily candle still carries a running value.
CLOSE_FINAL = time(16, 5)


class DailyCandleSource(Protocol):
    def get_daily_candle(self, symbol: str, target_date: date) -> object: ...


class LatestEventSource(Protocol):
    def hget(self, name: str, key: str) -> object: ...


def close_is_final(day: date, now: datetime | None) -> bool:
    now_et = (now or datetime.now(ET)).astimezone(ET)
    if day == now_et.date() and now_et.time() < CLOSE_FINAL:
        logger.error(
            "Official close for %s is not final before %s ET", day, CLOSE_FINAL
        )
        return False
    return True


def live_official_close(
    latest: LatestEventSource, day: date, now: datetime | None = None
) -> float | None:
    """Official SPX close for today's session from the Redis latest hash.

    The subscribe service keeps the feed's current daily candle there; its
    close is the official close once the index has stopped printing. The
    candle's own date is checked against ``day`` so a stale entry from an
    earlier session is never used.
    """
    if not close_is_final(day, now):
        return None
    raw = latest.hget(LATEST_CANDLES_KEY, DAILY_SYMBOL)
    if raw is None:
        logger.error("No %s candle in the Redis latest hash", DAILY_SYMBOL)
        return None
    try:
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        candle = CandleEvent.model_validate(json.loads(text))
    except (ValueError, TypeError) as exc:
        logger.error(
            "Unreadable %s candle in the Redis latest hash: %s", DAILY_SYMBOL, exc
        )
        return None
    if candle.time.date() != day or candle.close is None:
        logger.error(
            "Redis %s candle is dated %s with close %s; refusing to settle %s",
            DAILY_SYMBOL,
            candle.time,
            candle.close,
            day,
        )
        return None
    return float(candle.close)


def official_close(
    source: DailyCandleSource, day: date, now: datetime | None = None
) -> float | None:
    """Official SPX close for a past session from the InfluxDB daily candle.

    ``get_daily_candle`` walks back to earlier trading days when the target
    date has no candle; that is exactly the substitution a settlement must
    never make, so the candle's own date is checked against ``day``.
    """
    if not close_is_final(day, now):
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
