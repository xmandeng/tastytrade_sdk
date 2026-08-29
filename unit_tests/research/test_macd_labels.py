"""Nightly MACD-state labeling (post-hoc, forward-evidence only)."""

from research.tt156_zero_dte_butterfly.report import (
    macd_state_label,
    strategy_block,
)


class TestMacdStateLabel:
    def test_agree_bullish(self) -> None:
        assert macd_state_label(1.5, 0.0, "BULLISH") == "agree"

    def test_agree_bearish(self) -> None:
        assert macd_state_label(-1.5, 0.0, "BEARISH") == "agree"

    def test_converge_within_ten_bars(self) -> None:
        # opposing hist -2.0 closing at +0.5/bar -> flip ETA 4 bars
        assert macd_state_label(-2.0, 0.5, "BULLISH") == "converge"

    def test_oppose_slow_convergence_is_diverge(self) -> None:
        # ETA 40 bars is not converging in any tradable sense
        assert macd_state_label(-2.0, 0.05, "BULLISH") == "diverge"

    def test_oppose_moving_away_is_diverge(self) -> None:
        assert macd_state_label(-2.0, -0.5, "BULLISH") == "diverge"

    def test_zero_slope_is_diverge(self) -> None:
        assert macd_state_label(-2.0, 0.0, "BULLISH") == "diverge"


class TestStrategyBlockLabels:
    def make_row(self) -> dict:
        return {
            "variant": "w25_5m_m0_kal",
            "direction": "BULLISH",
            "short_strike": 7700.0,
            "width": 25.0,
            "opened_at": "2026-08-28T10:15:00-04:00",
            "entry_credit": 8.5,
            "entry_legs": [],
            "completion_legs": [],
            "completion_credit": None,
            "close_reason": "signal_hull",
            "outcome": "closed",
            "pnl_points": 1.0,
        }

    def test_label_column_rendered(self) -> None:
        row = self.make_row()
        lines = strategy_block([row], 7700.0, macd_labels={row["opened_at"]: "agree"})
        table = "\n".join(lines)
        assert "| 5m MACD |" in table
        assert "| agree |" in table

    def test_missing_label_shows_dash(self) -> None:
        row = self.make_row()
        lines = strategy_block([row], 7700.0, macd_labels={})
        assert "| — |" in "\n".join(lines)
