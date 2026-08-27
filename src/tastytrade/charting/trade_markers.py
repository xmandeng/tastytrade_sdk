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


def ledger_context(day_dir: Path) -> tuple[dict, dict, float | None, Any, Any]:
    """Final per-structure ledger rows for tooltip detail, via the report's
    own accounting (events_only_day / classify_first_entries / cell_all_in /
    order_outcome / usd) so tooltip numbers always match REPORT.md. Returns
    empty context if the research package is unavailable."""
    try:
        from research.tt156_zero_dte_butterfly.report import (
            STRATEGY_FAMS,
            cell_all_in,
            classify_first_entries,
            events_only_day,
            order_outcome,
            usd,
        )
    except ImportError:
        return {}, {}, None, None, None
    try:
        rows, _, settle = events_only_day(day_dir)
    except (OSError, KeyError, ValueError, TypeError):
        logger.exception("Ledger context unavailable for %s", day_dir)
        return {}, {}, None, None, None
    strat = [r for r in rows if r["variant"] in STRATEGY_FAMS]
    first = classify_first_entries(strat) if strat else {}
    by_open: dict[str, list[dict]] = {}
    for r in strat:
        by_open.setdefault(r["opened_at"], []).append(r)
    for group in by_open.values():
        group.sort(key=lambda r: r["width"])

    def all_in(r: dict) -> str:
        if settle is None:
            d = (r.get("pnl_points") or 0.0) * 100
            return f"-${abs(d):,.0f}" if d < 0 else f"${d:,.0f}"
        return usd(cell_all_in([r], settle))

    return by_open, first, settle, all_in, order_outcome


def order_text(r: dict) -> str:
    K, w = r["short_strike"], r["width"]
    if r["direction"] == "BEARISH":
        return f"SOLD {K:g}/{K + w:g} call spread"
    return f"SOLD {K:g}/{K - w:g} put spread"


def load_trade_markers(symbol: str, chart_date: date_type) -> list[dict[str, Any]]:
    """Marker dicts (UTC-epoch times) for one chart day, oldest first.

    Each marker is semantic — ``kind`` (entry/close/fly/tent), ``dir``
    (bull/bear, entries and closes only), ``text``, ``price`` (the spot at
    the event, so the frontend can pin it where the trade occurred; None
    for closes, which anchor to their bar), ``details`` (ledger-language
    lines for the hover tooltip, mirroring the daily report's per-order
    rows) — and the frontend owns all styling. Entries also carry
    ``strike`` and ``end`` (epoch when the structure closed or settled).
    Strategy-family trades only. Sibling widths sharing a timestamp
    collapse into one marker so the chart stays readable. Returns [] for
    non-SPX symbols or days without an event log.
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
    ends: dict[str, int] = {}
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
                    ends[e["opened_at"]] = max(
                        ends.get(e["opened_at"], 0), to_epoch(e["closed_at"])
                    )
                elif kind == "SETTLEMENT":
                    ends[e["opened_at"]] = max(
                        ends.get(e["opened_at"], 0), to_epoch(e["ts"])
                    )
                    if in_tent(e):
                        tents.setdefault(e["ts"], {**e, "widths": []})["widths"].append(
                            e["width"]
                        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        logger.exception("Unreadable trade event log: %s", path)
        return []

    by_open, first, settle, all_in, outcome_of = ledger_context(path.parent)

    def entry_details(opened_at: str) -> list[str]:
        if all_in is None:
            return []
        kind = "first entry" if first.get(opened_at, True) else "re-entry"
        return [
            f"{r['width']:g}-wide: {order_text(r)} · {kind} · "
            f"credit {r['entry_credit']:.2f} · all-in {all_in(r)} · "
            f"{outcome_of(r)}"
            for r in by_open.get(opened_at, [])
        ]

    def fly_details(e: dict) -> list[str]:
        if all_in is None:
            return []
        for r in by_open.get(e["opened_at"], []):
            if r["width"] == e["width"] and r.get("completion_credit") is not None:
                total = r["entry_credit"] + r["completion_credit"]
                return [
                    f"completion credit {r['completion_credit']:.2f} · "
                    f"total {total:.2f} vs {r['width']:g} wide · "
                    f"all-in {all_in(r)}"
                ]
        return []

    def close_details(e: dict) -> list[str]:
        if all_in is None:
            return []
        return [
            f"{r['width']:g}-wide: bought back @ {r['close_cost']:.2f} · "
            f"all-in {all_in(r)}"
            for r in by_open.get(e["opened_at"], [])
            if r.get("close_cost") is not None
        ]

    def tent_details(e: dict) -> list[str]:
        lines = []
        for r in by_open.get(e["opened_at"], []):
            if r.get("completion_credit") is None or settle is None:
                continue
            K, w = r["short_strike"], r["width"]
            if abs(settle - K) < w:
                line = f"settled {settle:g} in {K - w:g}/{K + w:g} tent"
                if all_in is not None:
                    line += f" · {w:g}-wide all-in {all_in(r)}"
                lines.append(line)
        return lines

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
                "price": e.get("entry_spot"),
                "strike": e["short_strike"],
                "end": ends.get(opened_at),
                "details": entry_details(opened_at),
            }
        )
    for e in completions:
        markers.append(
            {
                "time": to_epoch(e["completed_at"]),
                "kind": "fly",
                "text": f"FLY {e['width']:g}",
                "price": e.get("completion_spot"),
                "details": fly_details(e),
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
                "price": None,
                "details": close_details(e),
            }
        )
    for ts, e in tents.items():
        markers.append(
            {
                "time": to_epoch(ts),
                "kind": "tent",
                "text": f"TENT {widths_label(e['widths'])}",
                "price": e.get("settlement_spot"),
                "details": tent_details(e),
            }
        )
    return sorted(markers, key=lambda m: m["time"])
