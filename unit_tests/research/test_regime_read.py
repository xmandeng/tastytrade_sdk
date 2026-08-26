"""Regime read @ 11:00: morning features, frozen-calibration trend call, and
report block rendering incl. graceful degradation (TT-156, investigation
mode)."""

import gzip
import json
from pathlib import Path

import pytest

from research.tt156_zero_dte_butterfly import regime, report


def path_from(spots: list[float], start: int = 570) -> list[tuple[int, float]]:
    return [(start + i, s) for i, s in enumerate(spots)]


class TestMorningFeatures:
    def test_clean_drive_has_shallow_retrace(self) -> None:
        f = regime.morning_features(
            path_from([7700 + i * 0.5 for i in range(90)]), atr=60.0
        )
        assert f is not None
        assert f.net_pts == pytest.approx(44.5)
        assert f.retrace_frac < regime.RETRACE_Q25
        assert f.drive_atr == pytest.approx(44.5 / 60.0)

    def test_choppy_morning_has_deep_retrace(self) -> None:
        # oscillates 10 pts around flat, ending a hair above the open
        spots = [7700 + (10 if i % 2 else 0) for i in range(89)] + [7700.05]
        f = regime.morning_features(path_from(spots), atr=60.0)
        assert f is not None
        assert f.retrace_frac == pytest.approx(3.0)  # capped

    def test_sparse_morning_returns_none(self) -> None:
        assert regime.morning_features(path_from([7700.0] * 10), atr=60.0) is None

    def test_bars_outside_window_ignored(self) -> None:
        pre = [(500 + i, 9999.0) for i in range(30)]  # pre-market noise
        f = regime.morning_features(
            pre + path_from([7700 + i * 0.5 for i in range(60)]), atr=60.0
        )
        assert f is not None
        assert f.net_pts == pytest.approx(29.5)

    def test_no_atr_yields_no_drive(self) -> None:
        f = regime.morning_features(
            path_from([7700 + i * 0.5 for i in range(90)]), atr=None
        )
        assert f is not None and f.drive_atr is None


class TestTrendCall:
    def make(self, drive: float | None, retrace: float) -> regime.MorningFeatures:
        return regime.MorningFeatures(
            net_pts=10.0, drive_atr=drive, retrace_frac=retrace
        )

    def test_elevated_when_both_strong(self) -> None:
        assert regime.trend_call(self.make(0.7, 0.3)) == ("trend-elevated", 0.49)

    def test_unlikely_when_drive_weak(self) -> None:
        assert regime.trend_call(self.make(0.1, 1.0)) == ("trend-unlikely", 0.11)

    def test_unlikely_when_retrace_deep(self) -> None:
        assert regime.trend_call(self.make(0.7, 2.5)) == ("trend-unlikely", 0.11)

    def test_leaning_on_one_signal(self) -> None:
        assert regime.trend_call(self.make(0.7, 1.0)) == ("trend-leaning", 0.47)
        assert regime.trend_call(self.make(0.4, 0.3)) == ("trend-leaning", 0.47)

    def test_neutral_otherwise(self) -> None:
        assert regime.trend_call(self.make(0.4, 1.0)) == ("trend-neutral", 0.29)

    def test_no_atr_no_call(self) -> None:
        assert regime.trend_call(self.make(None, 0.3)) is None


def write_snapshots(day_dir: Path, spots: list[tuple[str, float]]) -> None:
    day_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(day_dir / "chain_snapshots.jsonl.gz", "wt", encoding="utf-8") as fh:
        for ts, spot in spots:
            fh.write(
                json.dumps(
                    {
                        "ts": ts,
                        "spot": spot,
                        "engine": {"SPX{=5m}": {"macd_position": "bullish"}},
                        "options": [],
                    }
                )
                + "\n"
            )


def minute_series(date: str, n: int, fn) -> list[tuple[str, float]]:
    return [
        (f"{date}T{9 + (30 + i) // 60:02d}:{(30 + i) % 60:02d}:00-04:00", fn(i))
        for i in range(n)
    ]


class TestRegimeBlock:
    def test_renders_call_with_prior_days_for_atr(self, tmp_path: Path) -> None:
        for d in range(1, 7):  # six prior sessions -> ATR available
            write_snapshots(
                tmp_path / f"2026-08-{d:02d}",
                minute_series(f"2026-08-{d:02d}", 380, lambda i: 7700 + (i % 60)),
            )
        today = tmp_path / "2026-08-11"
        write_snapshots(
            today, minute_series("2026-08-11", 90, lambda i: 7700 + i * 0.5)
        )
        snaps = report.load_snapshots(today)
        text = "\n".join(report.regime_read_block(snaps, today))
        assert "Regime read @ 11:00" in text
        assert "Call: trend-" in text
        assert "5m MACD one-sidedness" in text

    def test_degrades_without_prior_sessions(self, tmp_path: Path) -> None:
        today = tmp_path / "2026-08-11"
        write_snapshots(
            today, minute_series("2026-08-11", 90, lambda i: 7700 + i * 0.5)
        )
        snaps = report.load_snapshots(today)
        text = "\n".join(report.regime_read_block(snaps, today))
        assert "No trend call" in text  # features render, ATR missing

    def test_degrades_on_sparse_morning(self, tmp_path: Path) -> None:
        today = tmp_path / "2026-08-11"
        write_snapshots(today, minute_series("2026-08-11", 5, lambda _i: 7700.0))
        snaps = report.load_snapshots(today)
        text = "\n".join(report.regime_read_block(snaps, today))
        assert "insufficient morning data" in text


class TestRollingState:
    def test_reads_full_path_not_just_morning(self) -> None:
        # 9:30 -> 14:00: steady climb; rolling state sees all of it
        path = [(570 + i, 7700 + i * 0.5) for i in range(270)]
        state = regime.rolling_state(path, atr=60.0)
        assert state is not None
        assert state["drive_atr"] == pytest.approx(269 * 0.5 / 60.0)
        retrace = state["retrace_frac"]
        assert retrace is not None and retrace < 0.1

    def test_young_session_returns_none(self) -> None:
        assert regime.rolling_state([(570, 7700.0)] * 10, atr=60.0) is None

    def test_no_atr_still_gives_retrace(self) -> None:
        path = [(570 + i, 7700 + i * 0.5) for i in range(60)]
        state = regime.rolling_state(path, atr=None)
        assert state is not None
        assert state["drive_atr"] is None
        assert state["retrace_frac"] is not None
