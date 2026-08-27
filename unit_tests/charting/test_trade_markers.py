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
        write_events(data_root, [entry("w25_5m_m0", 25.0)])
        assert load_trade_markers("NDX", DAY) == []

    def test_sibling_widths_collapse_into_one_entry_marker(
        self, data_root: Path
    ) -> None:
        write_events(data_root, [entry("w25_5m_m0", 25.0), entry("w50_5m_m0", 50.0)])
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
        base = entry("w25_5m_m0", 25.0, direction="BEARISH")
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
        base = entry("w25_5m_m0", 25.0)
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
        base = entry("w25_5m_m0", 25.0)
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
