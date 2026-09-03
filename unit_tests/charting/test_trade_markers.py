"""TT-156 trade markers: event-log → lightweight-charts marker pass-through."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tastytrade.charting.trade_markers import load_trade_markers

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
        **kw,
    }


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TT156_DATA_DIR", str(tmp_path))
    return tmp_path


class TestLoadTradeMarkers:
    def test_missing_day_and_foreign_symbol_return_empty(self, data_root: Path) -> None:
        assert load_trade_markers("SPX", DAY) == []
        write_events(data_root, [entry("w25_5m_m0_kal", 25.0)])
        assert load_trade_markers("NDX", DAY) == []

    def test_sibling_widths_collapse_into_one_entry_marker(
        self, data_root: Path
    ) -> None:
        write_events(
            data_root, [entry("w25_5m_m0_kal", 25.0), entry("w50_5m_m0_kal", 50.0)]
        )
        markers = load_trade_markers("SPX", DAY)
        assert len(markers) == 1
        m = markers[0]
        assert m["text"] == "S 7700P 25/50"
        assert m["kind"] == "entry"
        assert m["dir"] == "bull"
        expected = int(
            datetime.fromisoformat("2026-08-18T15:03:35-04:00")
            .astimezone(timezone.utc)
            .timestamp()
        )
        assert m["time"] == expected

    def test_non_strategy_variants_ignored(self, data_root: Path) -> None:
        write_events(data_root, [entry("w25_m_m0", 25.0), entry("w10_5m_m0", 10.0)])
        assert load_trade_markers("SPX", DAY) == []

    def test_full_lifecycle_markers_sorted(self, data_root: Path) -> None:
        base = entry("w25_5m_m0_kal", 25.0, direction="BEARISH")
        write_events(
            data_root,
            [
                base,
                {
                    **base,
                    "event": "COMPLETION",
                    "completed_at": "2026-08-18T15:20:00-04:00",
                    "completion_credit": 22.0,
                },
                {
                    **base,
                    "event": "SETTLEMENT",
                    "ts": "2026-08-18T16:15:00-04:00",
                    "completion_credit": 22.0,
                    "settlement_spot": 7690.0,
                },
            ],
        )
        markers = load_trade_markers("SPX", DAY)
        assert [m["text"] for m in markers] == ["S 7700C 25", "FLY 25", "TENT 25"]
        assert [m["kind"] for m in markers] == ["entry", "fly", "tent"]
        assert markers == sorted(markers, key=lambda m: m["time"])
        assert markers[0]["dir"] == "bear"

    def test_settlement_outside_wings_gets_no_tent_marker(
        self, data_root: Path
    ) -> None:
        base = entry("w25_5m_m0_kal", 25.0)
        write_events(
            data_root,
            [
                base,
                {
                    **base,
                    "event": "SETTLEMENT",
                    "ts": "2026-08-18T16:15:00-04:00",
                    "completion_credit": 22.0,
                    "settlement_spot": 7600.0,
                },
            ],
        )
        texts = [m["text"] for m in load_trade_markers("SPX", DAY)]
        assert texts == ["S 7700P 25"]

    def test_close_marker_labels_reason(self, data_root: Path) -> None:
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
                },
            ],
        )
        markers = load_trade_markers("SPX", DAY)
        assert markers[-1]["text"] == "EOD 25"
        assert markers[-1]["kind"] == "close"
        assert markers[-1]["dir"] == "bull"

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

    def test_eod_fly_dash_when_not_triggered(self, data_root: Path) -> None:
        from tastytrade.charting.trade_markers import pnl_summary

        write_events(data_root, [entry("w25_5m_m0_kal", 25.0)])
        pnl = pnl_summary(DAY)
        assert pnl is not None
        fly = pnl["arms"][2]
        assert fly["total"] is None and fly["open"] is False and fly["cycles"] == 0
