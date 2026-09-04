"""TT-156 trade markers: event-log → per-order chart markers."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tastytrade.charting.trade_markers import (
    fly_break_evens,
    load_trade_markers,
    long_fly_break_evens,
)

DAY = date(2026, 8, 18)


def write_events(root: Path, events: list[dict]) -> None:
    day_dir = root / DAY.isoformat()
    day_dir.mkdir(parents=True)
    with (day_dir / "events.jsonl").open("w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


def entry(variant: str, width: float, **kw) -> dict:
    return {
        "event": "ENTRY",
        "variant": variant,
        "direction": "BULLISH",
        "short_strike": 7700.0,
        "width": width,
        "opened_at": "2026-08-18T15:03:35-04:00",
        "entry_credit": 22.0,
        "entry_spot": 7701.5,
        **kw,
    }


def epoch(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).astimezone(timezone.utc).timestamp())


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TT156_DATA_DIR", str(tmp_path))
    return tmp_path


class TestBreakEvens:
    def test_short_iron_fly_break_evens_at_body_plus_minus_credit(self) -> None:
        assert fly_break_evens(7705.0, 25.0, 18.0) == [7687, 7723]

    def test_lossless_fly_reports_wing_strikes(self) -> None:
        assert fly_break_evens(7705.0, 25.0, 25.43) == [7680, 7730]

    def test_long_fly_break_evens_round_to_whole_points(self) -> None:
        assert long_fly_break_evens(7750.0, 25.0, 15.625) == [7741, 7759]


class TestLoadTradeMarkers:
    def test_missing_day_and_foreign_symbol_return_empty(self, data_root: Path) -> None:
        assert load_trade_markers("SPX", DAY) == []
        write_events(data_root, [entry("w25_5m_m0_kal", 25.0)])
        assert load_trade_markers("NDX", DAY) == []

    def test_sibling_arms_share_one_entry_marker(self, data_root: Path) -> None:
        write_events(
            data_root,
            [
                entry("w50_5m_m0_kal", 50.0, entry_credit=30.0),
                entry("w25_5m_m0_kal", 25.0),
            ],
        )
        markers = load_trade_markers("SPX", DAY)
        assert len(markers) == 1
        m = markers[0]
        assert m["kind"] == "entry"
        assert m["n"] == 1
        assert m["dir"] == "bull"
        assert m["time"] == epoch("2026-08-18T15:03:35-04:00")
        assert m["price"] == 7701.5
        # Narrow arm first, spread text is short/long strike plus type.
        assert m["legs"] == [
            {"arm": "w25", "spread": "7700/7675 P", "credit": 22.0},
            {"arm": "w50", "spread": "7700/7650 P", "credit": 30.0},
        ]

    def test_non_strategy_and_early_fly_variants_ignored(self, data_root: Path) -> None:
        write_events(
            data_root,
            [
                entry("w25_m_m0", 25.0),
                entry("w10_5m_m0", 10.0),
                entry("w25_5m_m0_kal_ef5", 25.0),
            ],
        )
        assert load_trade_markers("SPX", DAY) == []

    def test_flip_yields_close_and_entry_with_own_numbers(
        self, data_root: Path
    ) -> None:
        first = entry("w25_5m_m0_kal", 25.0, direction="BEARISH")
        second = entry(
            "w25_5m_m0_kal",
            25.0,
            opened_at="2026-08-18T15:20:00-04:00",
            short_strike=7710.0,
            entry_credit=9.5,
        )
        write_events(
            data_root,
            [
                first,
                {
                    **first,
                    "event": "CLOSE",
                    "closed_at": "2026-08-18T15:20:00-04:00",
                    "close_reason": "signal_kalman",
                    "close_cost": 24.5,
                },
                second,
            ],
        )
        markers = load_trade_markers("SPX", DAY)
        assert [(m["kind"], m["n"]) for m in markers] == [
            ("entry", 1),
            ("close", 1),
            ("entry", 2),
        ]
        close = markers[1]
        assert close["reason"] == "kalman flip"
        assert close["price"] is None
        assert close["legs"][0]["spread"] == "7700/7725 C"
        assert close["legs"][0]["credit"] == 22.0
        assert close["legs"][0]["cost"] == 24.5
        assert markers[2]["legs"][0]["spread"] == "7710/7685 P"

    def test_close_reason_labels(self, data_root: Path) -> None:
        base = entry("w25_5m_m0_kal", 25.0)
        write_events(
            data_root,
            [
                base,
                {
                    **base,
                    "event": "CLOSE",
                    "closed_at": "2026-08-18T15:45:06-04:00",
                    "close_reason": "forced_eod",
                    "close_cost": 1.0,
                },
            ],
        )
        markers = load_trade_markers("SPX", DAY)
        assert markers[-1]["kind"] == "close"
        assert markers[-1]["reason"] == "forced EOD"

    def test_completion_becomes_fly_marker_with_break_evens(
        self, data_root: Path
    ) -> None:
        base = entry("w25_5m_m0_kal", 25.0, entry_credit=7.5)
        write_events(
            data_root,
            [
                base,
                {
                    **base,
                    "event": "COMPLETION",
                    "completed_at": "2026-08-18T15:20:00-04:00",
                    "completion_credit": 10.0,
                    "completion_spot": 7712.0,
                },
            ],
        )
        markers = load_trade_markers("SPX", DAY)
        assert [m["kind"] for m in markers] == ["entry", "fly"]
        fly = markers[1]
        assert fly["n"] == 1
        assert fly["arm"] == "w25"
        assert fly["price"] == 7712.0
        assert fly["strikes"] == [7675.0, 7700.0, 7725.0]
        assert fly["credit"] == 17.5
        assert fly["lossless"] is False
        assert fly["breakEvens"] == [7682, 7718]

    def test_lossless_completion_flagged(self, data_root: Path) -> None:
        base = entry("w25_5m_m0_kal", 25.0, entry_credit=7.5)
        write_events(
            data_root,
            [
                base,
                {
                    **base,
                    "event": "COMPLETION",
                    "completed_at": "2026-08-18T15:20:00-04:00",
                    "completion_credit": 18.0,
                },
            ],
        )
        fly = load_trade_markers("SPX", DAY)[1]
        assert fly["lossless"] is True
        assert fly["breakEvens"] == [7675, 7725]

    def test_eod_fly_gets_the_next_number(self, data_root: Path) -> None:
        write_events(
            data_root,
            [
                entry("w25_5m_m0_kal", 25.0),
                {
                    "event": "ENTRY",
                    "variant": "pinfly25_all",
                    "direction": "NEUTRAL",
                    "short_strike": 7750.0,
                    "width": 25.0,
                    "opened_at": "2026-08-18T14:00:10-04:00",
                    "entry_credit": -15.625,
                    "entry_spot": 7751.4,
                },
            ],
        )
        markers = load_trade_markers("SPX", DAY)
        # Sorted by time: the 14:00 fly precedes the 15:03 entry but keeps
        # the number after every vertical structure.
        assert [(m["kind"], m["n"]) for m in markers] == [("eod_fly", 2), ("entry", 1)]
        fly = markers[0]
        assert fly["arm"] == "w25"
        assert fly["strikes"] == [7725.0, 7750.0, 7775.0]
        assert fly["debit"] == 15.63
        assert fly["breakEvens"] == [7741, 7759]
        assert fly["price"] == 7751.4

    def test_corrupt_log_returns_empty(self, data_root: Path) -> None:
        day_dir = data_root / DAY.isoformat()
        day_dir.mkdir(parents=True)
        (day_dir / "events.jsonl").write_text("{not json\n")
        assert load_trade_markers("SPX", DAY) == []


class TestPnlSummary:
    """Day-P&L card data: per-arm totals via the report's own accounting."""

    def test_missing_day_returns_none(self, data_root: Path) -> None:
        from tastytrade.charting.trade_markers import pnl_summary

        assert pnl_summary(DAY) is None

    def test_settled_day_totals_and_tent(self, data_root: Path) -> None:
        from tastytrade.charting.trade_markers import pnl_summary

        base = {
            "direction": "BULLISH",
            "short_strike": 7700.0,
            "opened_at": "2026-08-18T15:03:35-04:00",
            "entry_credit": 12.0,
            "entry_legs": [{}, {}],
        }
        write_events(
            data_root,
            [
                # w25: settled in the tent (completed fly, settle between wings)
                {
                    "event": "SETTLEMENT",
                    "variant": "w25_5m_m0_kal",
                    "width": 25.0,
                    "status": "SETTLED",
                    "completion_credit": 14.0,
                    "completion_legs": [{}, {}],
                    "pnl_points": 3.0,
                    "settlement_spot": 7705.0,
                    **base,
                },
                # w50: flip-exit scratch
                {
                    "event": "CLOSE",
                    "variant": "w50_5m_m0_kal",
                    "width": 50.0,
                    "status": "CLOSED",
                    "closed_at": "2026-08-18T15:33:35-04:00",
                    "close_reason": "signal_kalman",
                    "pnl_points": -1.5,
                    **base,
                },
            ],
        )
        pnl = pnl_summary(DAY)
        assert pnl is not None and pnl["settled"] is True
        w25, w50, _fly = pnl["arms"]
        assert (w25["label"], w25["cycles"], w25["tents"]) == ("25-wide", 1, 1)
        assert w25["total"] > 0 and w25["open"] is False
        assert (w50["label"], w50["cycles"], w50["tents"]) == ("50-wide", 1, 0)
        assert w50["total"] < 0
        # peak margin = width − entry credit per lot, in dollars
        assert w25["margin"] == 1300 and w50["margin"] == 3800
        assert _fly["margin"] is None

    def test_peak_margin_sums_overlapping_verticals(self, data_root: Path) -> None:
        from tastytrade.charting.trade_markers import pnl_summary

        first = entry("w25_5m_m0_kal", 25.0, entry_credit=10.0, status="OPEN")
        second = entry(
            "w25_5m_m0_kal",
            25.0,
            opened_at="2026-08-18T15:20:35-04:00",
            entry_credit=8.0,
            status="OPEN",
        )
        # the first vertical completes into a lossless fly before the second
        # opens: its margin drops to zero, so the peak is the larger single
        # vertical, not the sum
        completed = {
            **first,
            "event": "COMPLETION",
            "completed_at": "2026-08-18T15:10:35-04:00",
            "completion_credit": 16.0,
            "status": "COMPLETED",
        }
        write_events(data_root, [first, completed, second])
        pnl = pnl_summary(DAY)
        assert pnl is not None
        assert pnl["arms"][0]["margin"] == 1700  # 25 − 8, the second vertical

        # same two verticals with the first still open: margins stack
        import shutil

        shutil.rmtree(data_root / DAY.isoformat())
        write_events(data_root, [first, second])
        pnl = pnl_summary(DAY)
        assert pnl is not None
        assert pnl["arms"][0]["margin"] == 3200  # (25 − 10) + (25 − 8)

    def test_open_vertical_flagged_midsession(self, data_root: Path) -> None:
        from tastytrade.charting.trade_markers import pnl_summary

        write_events(
            data_root,
            [
                {
                    "event": "ENTRY",
                    "variant": "w25_5m_m0_kal",
                    "direction": "BULLISH",
                    "short_strike": 7700.0,
                    "width": 25.0,
                    "opened_at": "2026-08-18T15:03:35-04:00",
                    "entry_credit": 12.0,
                    "entry_legs": [{}, {}],
                    "status": "OPEN",
                    "pnl_points": None,
                }
            ],
        )
        pnl = pnl_summary(DAY)
        assert pnl is not None and pnl["settled"] is False
        w25 = pnl["arms"][0]
        assert w25["open"] is True
        assert w25["total"] is None and w25["cycles"] == 0
        assert w25["margin"] == 1300  # open vertical already consumes margin

    def test_eod_fly_line_item(self, data_root: Path) -> None:
        from tastytrade.charting.trade_markers import pnl_summary

        write_events(
            data_root,
            [
                {
                    "event": "SETTLEMENT",
                    "variant": "pinfly25_all",
                    "direction": "PIN",
                    "short_strike": 7700.0,
                    "width": 25.0,
                    "opened_at": "2026-08-18T14:00:05-04:00",
                    "entry_credit": -3.1,
                    "entry_legs": [
                        {"occ_strike": 7675.0},
                        {"occ_strike": 7700.0},
                        {"occ_strike": 7700.0},
                        {"occ_strike": 7725.0},
                    ],
                    "status": "SETTLED",
                    "pnl_points": 7.4,
                    "settlement_spot": 7705.0,
                }
            ],
        )
        pnl = pnl_summary(DAY)
        assert pnl is not None
        fly = pnl["arms"][2]
        assert fly["label"] == "EOD fly"
        assert fly["cycles"] == 1 and fly["open"] is False
        assert 600 < fly["total"] < 740  # 7.4 pts minus fly friction
        assert fly["margin"] == 310  # the debit is the fly's full requirement

    def test_eod_fly_dash_when_not_triggered(self, data_root: Path) -> None:
        from tastytrade.charting.trade_markers import pnl_summary

        write_events(data_root, [entry("w25_5m_m0_kal", 25.0)])
        pnl = pnl_summary(DAY)
        assert pnl is not None
        fly = pnl["arms"][2]
        assert fly["total"] is None and fly["open"] is False and fly["cycles"] == 0
