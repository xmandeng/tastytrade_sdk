"""Flip-ETA gate: ETA arithmetic, bucket truth table, and report block
rendering for tagged, legacy (pre-gate), and mixed days (TT-156, plan
approved 2026-08-08)."""

import json
from pathlib import Path

import pytest

from research.tt156_zero_dte_butterfly import report
from research.tt156_zero_dte_butterfly.gate import flip_eta, gate_bucket


class TestFlipEta:
    def test_converging_returns_bars_to_cross(self) -> None:
        # hist -0.6 rising +0.2/bar -> crosses zero in 3 bars
        assert flip_eta(-0.6, 0.2) == pytest.approx(3.0)

    def test_converging_from_above(self) -> None:
        assert flip_eta(0.5, -0.25) == pytest.approx(2.0)

    def test_diverging_has_no_eta(self) -> None:
        assert flip_eta(0.5, 0.1) is None
        assert flip_eta(-0.5, -0.1) is None

    def test_flat_slope_has_no_eta(self) -> None:
        assert flip_eta(0.5, 0.0) is None

    def test_unknown_inputs_have_no_eta(self) -> None:
        assert flip_eta(None, 0.1) is None
        assert flip_eta(0.5, None) is None

    def test_zero_hist_is_not_converging(self) -> None:
        # hist exactly on the line: hist * slope == 0 -> no ETA
        assert flip_eta(0.0, -0.1) is None


class TestGateBucket:
    def test_confirms_when_hist_agrees(self) -> None:
        assert gate_bucket(0.5, 0.1, "BULLISH") == "confirms"
        assert gate_bucket(-0.5, 0.1, "BEARISH") == "confirms"

    def test_imminent_within_three_bars(self) -> None:
        # bearish entry, 5m still bullish (+0.3) but falling 0.15/bar -> ETA 2
        assert gate_bucket(0.3, -0.15, "BEARISH") == "imminent"

    def test_near_between_three_and_ten(self) -> None:
        # ETA = 0.5 / 0.1 = 5
        assert gate_bucket(-0.5, 0.1, "BULLISH") == "near"

    def test_firm_when_far_or_diverging(self) -> None:
        assert gate_bucket(-2.0, 0.1, "BULLISH") == "firm"  # ETA 20
        assert gate_bucket(-0.5, -0.1, "BULLISH") == "firm"  # diverging
        assert gate_bucket(-0.5, 0.0, "BULLISH") == "firm"  # flat

    def test_unknown_hist_yields_none(self) -> None:
        assert gate_bucket(None, 0.1, "BULLISH") is None

    def test_threshold_boundaries_inclusive(self) -> None:
        assert gate_bucket(-0.3, 0.1, "BULLISH") == "imminent"  # ETA exactly 3
        assert gate_bucket(-1.0, 0.1, "BULLISH") == "near"  # ETA exactly 10


def make_structure(
    variant: str,
    pnl: float,
    bucket: str | None,
    eta: float | None = None,
    opened: str = "2026-08-10T12:10:00-04:00",
) -> dict:
    return {
        "variant": variant,
        "direction": "BULLISH",
        "short_strike": 7450.0,
        "width": float(variant[1:3].rstrip("_")),
        "opened_at": opened,
        "outcome": "closed",
        "pnl_points": pnl,
        "entry_legs": [{}, {}],
        "completion_legs": [],
        "gate_bucket": bucket,
        "gate_flip_eta_5m": eta,
    }


class TestGateReportBlock:
    def test_legacy_day_renders_inactive_message(self, tmp_path: Path) -> None:
        day = tmp_path / "2026-06-20"
        day.mkdir()
        recon = [make_structure("w10_m_m0", 1.0, bucket=None)]
        text = "\n".join(report.flip_eta_gate_block(recon, 7440.0, day))
        assert "gate tracking not active" in text

    def test_tagged_day_renders_cluster_and_summaries(self, tmp_path: Path) -> None:
        day = tmp_path / "2026-08-10"
        day.mkdir()
        recon = [
            make_structure("w10_m_m0", 2.0, "near", 4.2),
            make_structure("w25_m_m0", 3.0, "near", 4.2),
            make_structure(
                "w10_m_m2", -1.0, "firm", None, opened="2026-08-10T13:00:00-04:00"
            ),
        ]
        text = "\n".join(report.flip_eta_gate_block(recon, 7440.0, day))
        assert "| 12:10 | BULLISH | near | 4.2 |" in text
        assert "gated (imminent+near)" in text
        assert "Cumulative since inception" in text
        assert "**Total**" not in text  # no lumped grand total

    def test_mixed_day_splits_gated_from_ungated(self, tmp_path: Path) -> None:
        day = tmp_path / "2026-08-10"
        day.mkdir()
        recon = [
            make_structure("w10_m_m0", 2.0, "imminent", 1.5),
            make_structure(
                "w10_m_m2", -4.0, "confirms", None, opened="2026-08-10T14:00:00-04:00"
            ),
        ]
        text = "\n".join(report.flip_eta_gate_block(recon, 7440.0, day))
        gated_row = next(
            line for line in text.splitlines() if "gated (imminent+near)" in line
        )
        ungated_row = next(
            line for line in text.splitlines() if line.startswith("| ungated")
        )
        # +2.0 pts closed = 2 spread orders of friction -> 2.0 - 0.25 = $175
        assert "$175" in gated_row
        # -4.0 - 0.25 -> -$425
        assert "-$425" in ungated_row

    def test_cumulative_reads_sibling_tagged_days(self, tmp_path: Path) -> None:
        prior = tmp_path / "2026-08-08"
        prior.mkdir()
        entry = make_structure(
            "w10_m_m0", 1.5, "imminent", 2.0, opened="2026-08-08T10:30:00-04:00"
        )
        entry.update({"event": "ENTRY", "status": "CLOSED", "ts": entry["opened_at"]})
        (prior / "events.jsonl").write_text(json.dumps(entry) + "\n")
        day = tmp_path / "2026-08-10"
        day.mkdir()
        recon = [make_structure("w25_m_m0", 2.0, "near", 5.0)]
        text = "\n".join(report.flip_eta_gate_block(recon, 7440.0, day))
        assert "1 tagged sessions" in text
        # prior day's gated w10: 1.5 - 0.25 pts = $125
        assert "$125" in text
