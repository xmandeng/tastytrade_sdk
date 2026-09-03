"""TT-156 paper-trade markers for the chart (pure reader).

Reads the research harness's per-day event log (events.jsonl) and converts
the primary strategy trades — kalman-tangent 5m, 25/50-wide — into
lightweight-charts marker dicts. The chart server passes them through in
the init payload; nothing is computed beyond grouping, and no store is
written.
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
STRATEGY_VARIANTS = ("w25_5m_m0_kal", "w25_5m_m0_kal_ef5", "w50_5m_m0_kal")
DATA_DIR_ENV = "TT156_DATA_DIR"
DEFAULT_DATA_DIR = "research_data/TT-156"


def events_path(chart_date: date_type) -> Path:
    root = Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
    return root / chart_date.isoformat() / "events.jsonl"


def to_epoch(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).timestamp())


def widths_label(widths: list[float]) -> str:
    return "/".join(f"{w:g}" for w in sorted(set(widths)))


def arm_label(row: dict) -> str:
    suffix = " (early-fly)" if str(row.get("variant", "")).endswith("_ef5") else ""
    return f"{row['width']:g}-wide{suffix}"


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
    strat = [r for r in rows if r["variant"] in STRATEGY_VARIANTS]
    first = classify_first_entries(strat) if strat else {}
    by_open: dict[str, list[dict]] = {}
    for r in strat:
        by_open.setdefault(r["opened_at"], []).append(r)
    for group in by_open.values():
        group.sort(key=lambda r: r["width"])

    def all_in(r: dict) -> str:
        # Mid-session (settle unknown) still applies the cost model — the
        # chip nets, the P&L card, and REPORT.md must never disagree.
        return usd(cell_all_in([r], settle or 0.0))

    return by_open, first, settle, all_in, order_outcome


def order_text(r: dict) -> str:
    K, w = r["short_strike"], r["width"]
    if r["direction"] == "BEARISH":
        return f"SOLD {K:g}/{K + w:g} call spread"
    return f"SOLD {K:g}/{K - w:g} put spread"


PNL_ARMS = (("w25_5m_m0_kal", "25-wide"), ("w50_5m_m0_kal", "50-wide"))
# The 14:00 long ATM butterfly, bought every session by decision (the
# no-tent-only sibling stays in the grid as a tracked alternative).
PNL_EOD_FLY = ("pinfly25_all", "EOD fly")


def latest_structures(events: list[dict]) -> list[dict]:
    """One dict per structure — its most recent ledger event — so margin can
    be traced for verticals still open, not only for settled cycles."""
    latest: dict[str, dict] = {}
    for e in events:
        if e.get("event") in ("ENTRY", "COMPLETION", "CLOSE", "SETTLEMENT"):
            latest[e["opened_at"]] = e
    return list(latest.values())


def pnl_summary(chart_date: date_type) -> dict[str, Any] | None:
    """Per-arm day P&L for the chart's floating tracker card.

    Same accounting as REPORT.md (events_only_day / cell_all_in), so the
    card and the nightly report never disagree. Mid-session (no settlement
    yet) the totals cover realized cycles only, and the tent count falls
    back to locked flies still riding to settlement. ``margin`` is the arm's
    peak concurrent buying-power reduction so far in the day (the
    scoreboard's high-water margin), in dollars per lot.
    """
    path = events_path(chart_date)
    if not path.exists():
        return None
    try:
        from research.tt156_zero_dte_butterfly.report import (
            cell_all_in,
            events_only_day,
            margin_high_water,
            pinfly_all_in,
            settled_in_tent,
        )
    except ImportError:
        return None
    try:
        rows, _, settle = events_only_day(path.parent)
        raw = [
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        ]
    except (OSError, KeyError, ValueError, TypeError):
        logger.exception("P&L summary unavailable for %s", path)
        return None
    arms: list[dict[str, Any]] = []
    for variant, label in PNL_ARMS:
        sub = [r for r in rows if r["variant"] == variant]
        events = [e for e in raw if e.get("variant") == variant]
        entries = sum(1 for e in events if e.get("event") == "ENTRY")
        terminal = sum(1 for e in events if e.get("event") in ("CLOSE", "SETTLEMENT"))
        if settle is not None:
            tents = sum(1 for r in sub if settled_in_tent(r, settle))
        else:
            tents = sum(1 for e in events if e.get("event") == "COMPLETION")
        structures = latest_structures(events)
        arms.append(
            {
                "label": label,
                "total": round(cell_all_in(sub, settle or 0.0) * 100) if sub else None,
                "cycles": len(sub),
                "open": entries > terminal,
                "tents": tents,
                "margin": (
                    round(margin_high_water(structures) * 100) if structures else None
                ),
            }
        )
    variant, label = PNL_EOD_FLY
    sub = [r for r in rows if r["variant"] == variant]
    events = [e for e in raw if e.get("variant") == variant]
    entries = sum(1 for e in events if e.get("event") == "ENTRY")
    terminal = sum(1 for e in events if e.get("event") in ("CLOSE", "SETTLEMENT"))
    arms.append(
        {
            "label": label,
            "total": round(pinfly_all_in(sub, settle or 0.0) * 100) if sub else None,
            "cycles": len(sub),
            "open": entries > terminal,
            "tents": 0,
            # A long fly's requirement is its debit (entry_credit is negative)
            "margin": (
                round(max(-s["entry_credit"] for s in latest_structures(events)) * 100)
                if events
                else None
            ),
        }
    )
    return {"arms": arms, "settled": settle is not None}


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
    completions: dict[tuple[str, float, bool], dict] = {}
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
                    # sibling arms completing on the same snapshot at the same
                    # width collapse; early-fly conversions stay distinct
                    comp_key = (e["completed_at"], e["width"], bool(e.get("early_fly")))
                    completions.setdefault(comp_key, e)
                elif kind == "CLOSE":
                    close_key = (e["closed_at"], str(e.get("close_reason")))
                    closes.setdefault(close_key, {**e, "widths": []})["widths"].append(
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

    def cycle_story(r: dict) -> str:
        """Plain-language cycle commentary for the visual history."""
        if r.get("completion_credit") is not None:
            formed = (
                "converted early into a deficit fly"
                if r.get("early_fly")
                else "formed a butterfly"
            )
            if r.get("outcome") == "settled" and settle is not None:
                where = (
                    "settled in the tent"
                    if abs(settle - r["short_strike"]) < r["width"]
                    else "settled outside the tent"
                )
                return f"{formed} · {where}"
            return formed
        reason = r.get("close_reason")
        if reason == "forced_eod":
            return "forced close at 15:45"
        if reason == "signal_hull":
            return "closed early on hull flip (backstop)"
        if reason == "signal_kalman":
            return "closed early on kalman flip"
        return str(outcome_of(r)) if outcome_of is not None else "open"

    def entry_details(opened_at: str) -> list[str]:
        if all_in is None:
            return []
        kind = "first entry" if first.get(opened_at, True) else "re-entry"
        return [
            f"{arm_label(r)}: {order_text(r)} · {kind} · "
            f"credit {r['entry_credit']:.2f} · {cycle_story(r)} · "
            f"net {all_in(r)}"
            for r in by_open.get(opened_at, [])
        ]

    def fly_details(e: dict) -> list[str]:
        if all_in is None:
            return []
        for r in by_open.get(e["opened_at"], []):
            if r["variant"] == e["variant"] and r.get("completion_credit") is not None:
                total = r["entry_credit"] + r["completion_credit"]
                prefix = (
                    "early conversion (bounded deficit) · "
                    if e.get("early_fly")
                    else ""
                )
                return [
                    f"{prefix}completion credit {r['completion_credit']:.2f} · "
                    f"total {total:.2f} vs {r['width']:g} wide · "
                    f"all-in {all_in(r)}"
                ]
        return []

    def close_details(e: dict) -> list[str]:
        if all_in is None:
            return []
        return [
            f"{arm_label(r)}: bought back @ {r['close_cost']:.2f} · all-in {all_in(r)}"
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
                    line += f" · {arm_label(r)} all-in {all_in(r)}"
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
    for (_, width, early), e in completions.items():
        markers.append(
            {
                "time": to_epoch(e["completed_at"]),
                "kind": "fly",
                "text": f"{'EF ' if early else ''}FLY {width:g}",
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
