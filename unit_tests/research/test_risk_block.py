"""Per-arm peak margin / open-structure tracking in the nightly report."""

from research.tt156_zero_dte_butterfly.report import risk_block, structure_margin


def structure(opened, closed=None, completed=None, credit=8.0, compl=None, width=25.0):
    return {
        "variant": "w25_5m_m0",
        "width": width,
        "entry_credit": credit,
        "opened_at": opened,
        "closed_at": closed,
        "completed_at": completed,
        "completion_credit": compl,
    }


class TestStructureMargin:
    def test_open_vertical(self) -> None:
        s = structure("T10:00")
        assert structure_margin(s, "T10:30") == 17.0  # 25 - 8

    def test_lossless_fly_frees_margin(self) -> None:
        s = structure("T10:00", completed="T11:00", compl=18.0)  # total 26 >= 25
        assert structure_margin(s, "T11:30") == 0.0

    def test_deficit_fly_keeps_shortfall(self) -> None:
        s = structure("T10:00", completed="T11:00", compl=12.0)  # total 20 < 25
        assert structure_margin(s, "T11:30") == 5.0

    def test_before_completion_full_margin(self) -> None:
        s = structure("T10:00", completed="T11:00", compl=18.0)
        assert structure_margin(s, "T10:30") == 17.0


class TestRiskBlock:
    def test_peak_concurrency_and_margin(self) -> None:
        rows = [
            structure("T10:00", closed="T11:00"),  # margin 17 until 11:00
            structure("T10:30"),  # margin 17, stays open
            structure("T11:30", completed="T12:00", compl=18.0),  # 17 then 0
        ]
        lines = risk_block(rows)
        table = "\n".join(lines)
        # peak: 10:30-11:00 -> two open verticals = 34 pts = $3,400
        assert "| w25_5m_m0 | $3,400 | 2 |" in table

    def test_empty_returns_nothing(self) -> None:
        assert risk_block([]) == []
