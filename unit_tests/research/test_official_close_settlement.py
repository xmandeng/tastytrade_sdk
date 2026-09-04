"""Settlement at the official SPX close: lookup guards and ledger restatement."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytest

from research.tt156_zero_dte_butterfly.config import ET
from research.tt156_zero_dte_butterfly.settlement import (
    official_close,
    restate_day,
    session_dirs,
    settled_pnl_points,
)

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


class TestSettledPnlPoints:
    def test_iron_fly_matches_simulator_formula(self) -> None:
        row = {
            "variant": "w25_5m_m0_kal",
            "short_strike": 7700.0,
            "width": 25.0,
            "entry_credit": 12.0,
            "completion_credit": 14.0,
        }
        assert settled_pnl_points(row, 7705.0) == pytest.approx(21.0)
        assert settled_pnl_points(row, 7600.0) == pytest.approx(1.0)  # capped at width

    def test_pin_fly_matches_pinfly_formula(self) -> None:
        row = {
            "variant": "pinfly25_all",
            "short_strike": 7710.0,
            "width": 25.0,
            "entry_credit": -15.775,
        }
        assert round(settled_pnl_points(row, 7718.6), 3) == round(25 - 8.6 - 15.775, 3)
        assert (
            settled_pnl_points(row, 7750.0) == -15.775
        )  # outside the wings: lose the debit


def write_ledger(day_dir: Path, rows: list[dict], results: dict | None) -> None:
    day_dir.mkdir(parents=True)
    (day_dir / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if results is not None:
        (day_dir / "final_results.json").write_text(json.dumps(results))


class TestRestateDay:
    def rows(self) -> list[dict]:
        base = {
            "direction": "BULLISH",
            "short_strike": 7710.0,
            "width": 25.0,
            "opened_at": "2026-09-04T11:45:10-04:00",
        }
        return [
            {
                "event": "ENTRY",
                "variant": "w25_5m_m0_kal",
                "entry_credit": 12.0,
                "status": "OPEN",
                **base,
            },
            {
                "event": "SETTLEMENT",
                "variant": "w25_5m_m0_kal",
                "entry_credit": 12.0,
                "completion_credit": 14.0,
                "status": "SETTLED",
                "pnl_points": 19.72,
                "settlement_spot": 7716.28,
                **base,
            },
            {
                "event": "SETTLEMENT",
                "variant": "pinfly25_all",
                "entry_credit": -15.775,
                "status": "SETTLED",
                "pnl_points": 2.945,
                **base,
            },  # no settlement_spot
            {
                "event": "CLOSE",
                "variant": "w50_5m_m0_kal",
                "entry_credit": 8.0,
                "status": "CLOSED",
                "pnl_points": 5.25,
                **base,
            },
        ]

    def test_rewrites_settled_rows_only(self, tmp_path: Path) -> None:
        day_dir = tmp_path / "2026-09-04"
        write_ledger(day_dir, self.rows(), {"settlement_spot": 7716.28, "cycles": 152})
        res = restate_day(day_dir, 7718.6)
        assert res.previous_spot == 7716.28 and res.rows_changed == 2
        out = [
            json.loads(line)
            for line in (day_dir / "events.jsonl").read_text().splitlines()
        ]
        iron, fly, close = out[1], out[2], out[3]
        assert iron["settlement_spot"] == 7718.6
        assert iron["pnl_points"] == pytest.approx(26.0 - 8.6)
        assert fly["settlement_spot"] == 7718.6
        assert round(fly["pnl_points"], 3) == round(25 - 8.6 - 15.775, 3)
        assert close["pnl_points"] == 5.25 and "settlement_spot" not in close
        assert out[0]["status"] == "OPEN"
        results = json.loads((day_dir / "final_results.json").read_text())
        assert results == {"settlement_spot": 7718.6, "cycles": 152}
        assert res.before["pinfly25_all"] == 2.945
        assert round(res.after["pinfly25_all"], 3) == 0.625

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        day_dir = tmp_path / "2026-09-04"
        write_ledger(day_dir, self.rows(), {"settlement_spot": 7716.28})
        before = (day_dir / "events.jsonl").read_text()
        res = restate_day(day_dir, 7718.6, dry_run=True)
        assert res.rows_changed == 2
        assert (day_dir / "events.jsonl").read_text() == before
        assert (
            json.loads((day_dir / "final_results.json").read_text())["settlement_spot"]
            == 7716.28
        )

    def test_missing_ledger_is_a_no_op(self, tmp_path: Path) -> None:
        day_dir = tmp_path / "2026-09-04"
        day_dir.mkdir()
        assert restate_day(day_dir, 7718.6).rows_changed == 0


class TestSessionDirs:
    def test_finds_days_and_pre_fix_archive_but_not_test_runs(
        self, tmp_path: Path
    ) -> None:
        for name in ("2026-09-03", "2026-09-04", "2026-09-04-test", "notes"):
            (tmp_path / name).mkdir()
        (tmp_path / "live_pre_fix" / "2026-06-11").mkdir(parents=True)
        names = [str(p.relative_to(tmp_path)) for p in session_dirs(tmp_path)]
        assert names == ["2026-09-03", "2026-09-04", "live_pre_fix/2026-06-11"]
