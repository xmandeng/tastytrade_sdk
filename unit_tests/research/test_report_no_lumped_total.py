"""The family x time block must never surface a lumped all-in total (no Total
row, no grand total) and must call out the most successful tranche. The grid is
a research instrument to find which tranche has edge, not a net-profitable
portfolio (user directive 2026-07-08)."""

from research.tt156_zero_dte_butterfly import report


def make_structure(variant: str, k: float, w: float, pnl: float) -> dict:
    return {
        "variant": variant,
        "direction": "BULLISH",
        "short_strike": k,
        "width": w,
        "opened_at": "2026-07-08T12:00:00",
        "outcome": "closed",
        "pnl_points": pnl,
        "entry_legs": [{}, {}],
        "completion_legs": [],
    }


def block_text() -> str:
    recon = [
        make_structure("w50_5m_m0", 7435, 50, 6.0),  # winning tranche
        make_structure("w10_m_m0", 7450, 10, -3.0),
    ]
    return "\n".join(report.tranche_timeframe_block(recon, 7440.0))


def test_no_lumped_total_row_or_grand_total() -> None:
    text = block_text()
    assert "**Total**" not in text  # no cross-family Total row
    # header row keeps a per-tranche total column, but no lumped total line
    assert text.count("Tranche total") == 1


def test_calls_out_most_successful_tranche() -> None:
    text = block_text()
    assert "Most successful tranche: 5m·w50" in text
