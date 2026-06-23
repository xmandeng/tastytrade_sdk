"""A no-trade session is a valid regime observation, so report generation must
not crash when the collector never wrote events.jsonl (no structures all day)."""

from pathlib import Path

from research.tt156_zero_dte_butterfly import report


def test_load_events_missing_file_returns_empty(tmp_path: Path) -> None:
    # No events.jsonl on disk — a session that never fired.
    assert report.load_events(tmp_path) == []


def test_load_events_skips_blank_lines(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_text(
        '{"event": "ENTRY", "variant": "w10_m_m0", "direction": "BEARISH", '
        '"opened_at": "2026-06-23T10:00:00"}\n\n'
    )
    events = report.load_events(tmp_path)
    assert len(events) == 1
    assert events[0]["variant"] == "w10_m_m0"


def test_reconstruct_structures_no_events_returns_empty(tmp_path: Path) -> None:
    # Snapshots exist but there were no entries, so nothing to reconstruct.
    snapshots = [{"ts": "2026-06-23T10:00:00-04:00", "spot": 7400.0, "options": []}]
    assert report.reconstruct_structures(tmp_path, snapshots, 7400.0) == []
