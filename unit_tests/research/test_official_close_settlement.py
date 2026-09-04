"""Settlement at the official SPX close: the lookup and its refusals."""

from dataclasses import dataclass
from datetime import date, datetime

from research.tt156_zero_dte_butterfly.config import ET
from research.tt156_zero_dte_butterfly.settlement import official_close

DAY = date(2026, 9, 4)
AFTER_CLOSE = datetime(2026, 9, 4, 16, 15, tzinfo=ET)


@dataclass
class Candle:
    time: datetime
    close: float | None


class Source:
    def __init__(self, candle: Candle | None) -> None:
        self.candle = candle

    def get_daily_candle(self, symbol: str, target_date: date) -> object:
        if self.candle is None:
            raise ValueError("no candle")
        return self.candle


class TestOfficialClose:
    def test_returns_close_dated_on_the_session(self) -> None:
        src = Source(Candle(datetime(2026, 9, 4), 7718.6))
        assert official_close(src, DAY, now=AFTER_CLOSE) == 7718.6

    def test_refuses_candle_from_an_earlier_day(self) -> None:
        # get_daily_candle walks back to the prior trading day when the
        # target is missing; a settlement must never take that substitute
        src = Source(Candle(datetime(2026, 9, 3), 7747.71))
        assert official_close(src, DAY, now=AFTER_CLOSE) is None

    def test_refuses_missing_candle_or_close(self) -> None:
        assert official_close(Source(None), DAY, now=AFTER_CLOSE) is None
        src = Source(Candle(datetime(2026, 9, 4), None))
        assert official_close(src, DAY, now=AFTER_CLOSE) is None

    def test_refuses_before_the_close_is_final(self) -> None:
        src = Source(Candle(datetime(2026, 9, 4), 7716.28))
        intraday = datetime(2026, 9, 4, 15, 59, 56, tzinfo=ET)
        assert official_close(src, DAY, now=intraday) is None
        # a past session is final regardless of the clock
        assert (
            official_close(src, DAY, now=datetime(2026, 9, 5, 9, 0, tzinfo=ET))
            == 7716.28
        )
