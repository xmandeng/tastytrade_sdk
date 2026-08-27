"""TT-156 paper-trade markers for the chart (pure reader).

Reads the research harness's per-day event log (events.jsonl) and converts
the strategy trades — 5m confluence, 25/50-wide — into lightweight-charts
marker dicts. The chart server passes them through in the init payload;
nothing is computed beyond grouping, and no store is written.
"""

import json
import logging
import os
from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MARKER_SYMBOL = "SPX"
STRATEGY_VARIANTS = ("w25_5m_m0", "w50_5m_m0")
DATA_DIR_ENV = "TT156_DATA_DIR"
DEFAULT_DATA_DIR = "research_data/TT-156"


def events_path(chart_date: date_type) -> Path:
    root = Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
    return root / chart_date.isoformat() / "events.jsonl"


def to_epoch(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).timestamp())


def widths_label(widths: list[float]) -> str:
    return "/".join(f"{w:g}" for w in sorted(set(widths)))


def in_tent(event: dict) -> bool:
    """Locked fly whose settlement landed strictly between its wings."""
    settle = event.get("settlement_spot")
    return (
        event.get("completion_credit") is not None
        and settle is not None
        and abs(settle - event["short_strike"]) < event["width"]
    )


def load_trade_markers(symbol: str, chart_date: date_type) -> list[dict[str, Any]]:
    """Marker dicts (UTC-epoch times) for one chart day, oldest first.

    Each marker is semantic — ``kind`` (entry/close/fly/tent), ``dir``
    (bull/bear, entries and closes only), ``text`` — and the frontend owns
    all styling. Strategy-family trades only. Sibling widths sharing a
    timestamp collapse into one marker so the chart stays readable. Returns
    [] for non-SPX symbols or days without an event log.
    """
    if symbol != MARKER_SYMBOL:
        return []
    path = events_path(chart_date)
    if not path.exists():
        return []

    entries: dict[str, dict] = {}
    completions: list[dict] = []
    closes: dict[tuple[str, str], dict] = {}
    tents: dict[str, dict] = {}
    try:
        with path.open() as fh:
            for line in fh:
                e = json.loads(line)
                if e.get("variant") not in STRATEGY_VARIANTS:
                    continue
                kind = e.get("event")
                if kind == "ENTRY":
                    entries.setdefault(e["opened_at"], {**e, "widths": []})[
                        "widths"
                    ].append(e["width"])
                elif kind == "COMPLETION":
                    completions.append(e)
                elif kind == "CLOSE":
                    key = (e["closed_at"], str(e.get("close_reason")))
                    closes.setdefault(key, {**e, "widths": []})["widths"].append(
                        e["width"]
                    )
                elif kind == "SETTLEMENT" and in_tent(e):
                    tents.setdefault(e["ts"], {**e, "widths": []})["widths"].append(
                        e["width"]
                    )
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        logger.exception("Unreadable trade event log: %s", path)
        return []

    markers: list[dict[str, Any]] = []
    for opened_at, e in entries.items():
        bull = e["direction"] == "BULLISH"
        cp = "P" if bull else "C"
        markers.append(
            {
                "time": to_epoch(opened_at),
                "kind": "entry",
                "dir": "bull" if bull else "bear",
                "text": f"S {e['short_strike']:g}{cp} {widths_label(e['widths'])}",
            }
        )
    for e in completions:
        markers.append(
            {
                "time": to_epoch(e["completed_at"]),
                "kind": "fly",
                "text": f"FLY {e['width']:g}",
            }
        )
    for (closed_at, reason), e in closes.items():
        label = "EOD" if reason == "forced_eod" else "FLIP"
        markers.append(
            {
                "time": to_epoch(closed_at),
                "kind": "close",
                "dir": "bull" if e["direction"] == "BULLISH" else "bear",
                "text": f"{label} {widths_label(e['widths'])}",
            }
        )
    for ts, e in tents.items():
        markers.append(
            {
                "time": to_epoch(ts),
                "kind": "tent",
                "text": f"TENT {widths_label(e['widths'])}",
            }
        )
    return sorted(markers, key=lambda m: m["time"])
