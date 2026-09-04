"""TT-156 paper-trade markers for the chart (pure reader).

Reads the research harness's per-day event log (events.jsonl) and converts
the primary strategy trades — kalman-tangent 5m, 25/50-wide — plus the
14:00 EOD fly into chart marker dicts, one per order event, numbered per
structure so an entry and its close share a number. The chart server
passes them through in the init payload; nothing is computed beyond
grouping and the fly break-even arithmetic, and no store is written.
"""

import json
import logging
import os
from decimal import ROUND_HALF_UP, Decimal
from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MARKER_SYMBOL = "SPX"
# The two card arms carry chips; the early-fly sibling is a tracked
# alternative that would only duplicate every row.
STRATEGY_VARIANTS = ("w25_5m_m0_kal", "w50_5m_m0_kal")
ARM_NAMES = {"w25_5m_m0_kal": "w25", "w50_5m_m0_kal": "w50"}
EOD_FLY_VARIANT = "pinfly25_all"
CLOSE_REASONS = {
    "signal_kalman": "kalman flip",
    "signal_hull": "hull flip",
    "forced_eod": "forced EOD",
}
DATA_DIR_ENV = "TT156_DATA_DIR"
DEFAULT_DATA_DIR = "research_data/TT-156"


def events_path(chart_date: date_type) -> Path:
    root = Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
    return root / chart_date.isoformat() / "events.jsonl"


def to_epoch(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).timestamp())


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
            pinfly_all_in,
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
    for r in rows:
        if r["variant"] in STRATEGY_VARIANTS or r["variant"] == EOD_FLY_VARIANT:
            by_open.setdefault(r["opened_at"], []).append(r)
    for group in by_open.values():
        group.sort(key=lambda r: r["width"])

    def all_in(r: dict) -> str:
        # Mid-session (settle unknown) still applies the cost model — the
        # chip nets, the P&L card, and REPORT.md must never disagree. The
        # long EOD fly has its own cost model.
        if r["variant"] == EOD_FLY_VARIANT:
            return usd(pinfly_all_in([r], settle or 0.0))
        return usd(cell_all_in([r], settle or 0.0))

    return by_open, first, settle, all_in, order_outcome


def spread_text(r: dict) -> str:
    """Short strike / long strike and the option type: ``7705/7680 P``."""
    K, w = r["short_strike"], r["width"]
    if r["direction"] == "BEARISH":
        return f"{K:g}/{K + w:g} C"
    return f"{K:g}/{K - w:g} P"


def round2(v: float) -> float:
    """Half-up to cents; float round() would show 15.625 as 15.62."""
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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


def fly_break_evens(body: float, width: float, credit: float) -> list[int]:
    """Short iron fly: P&L = credit − min(width, |S − K|), so the break evens
    sit at K ± credit; once the credit covers the width the fly is lossless
    and the wing strikes are reported instead. Whole points are enough for
    a chart annotation."""
    half = min(credit, width)
    return [round(body - half), round(body + half)]


def long_fly_break_evens(body: float, width: float, debit: float) -> list[int]:
    """Long fly: P&L = max(0, width − |S − K|) − debit → K ± (width − debit),
    rounded to whole points."""
    half = width - debit
    return [round(body - half), round(body + half)]


def load_trade_markers(symbol: str, chart_date: date_type) -> list[dict[str, Any]]:
    """Marker dicts (UTC-epoch times) for one chart day, oldest first.

    One marker per order event, numbered per structure (``n``) so an entry
    and its close share a number:

    * ``entry``   — ``dir`` bull/bear, ``price`` (entry spot), ``legs`` of
      ``{arm, spread, credit}`` for the sibling arms opened together.
    * ``close``   — ``reason`` and ``legs`` of ``{arm, spread, credit, cost,
      net}``; sibling arms closed on the same snapshot share a marker.
    * ``fly``     — the w25/w50 completion: ``strikes`` [lower wing, body,
      upper wing], net ``credit``, ``breakEvens`` and all-in ``net``.
    * ``eod_fly`` — the 14:00 long fly: ``strikes``, ``debit``,
      ``breakEvens`` and ``net``.

    ``net`` strings reuse the daily report's accounting so chart and
    REPORT.md agree. Returns [] for non-SPX symbols or days without a log.
    """
    if symbol != MARKER_SYMBOL:
        return []
    path = events_path(chart_date)
    if not path.exists():
        return []

    entries: dict[str, dict] = {}
    closes: dict[tuple[str, str], list[dict]] = {}
    completions: list[dict] = []
    eod: dict[str, dict] = {}
    try:
        with path.open() as fh:
            for line in fh:
                e = json.loads(line)
                variant = e.get("variant")
                kind = e.get("event")
                if variant == EOD_FLY_VARIANT:
                    if kind == "ENTRY":
                        eod.setdefault(e["opened_at"], e)
                    continue
                if variant not in STRATEGY_VARIANTS:
                    continue
                if kind == "ENTRY":
                    entries.setdefault(e["opened_at"], {**e, "arms": []})[
                        "arms"
                    ].append(e)
                elif kind == "CLOSE":
                    closes.setdefault((e["opened_at"], e["closed_at"]), []).append(e)
                elif kind == "COMPLETION":
                    completions.append(e)
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        logger.exception("Unreadable trade event log: %s", path)
        return []

    by_open, _first, _settle, all_in, _outcome = ledger_context(path.parent)

    def ledger_row(opened_at: str, variant: str) -> dict | None:
        for r in by_open.get(opened_at, []):
            if r["variant"] == variant:
                return r
        return None

    def net_of(opened_at: str, variant: str) -> str | None:
        r = ledger_row(opened_at, variant)
        return all_in(r) if (r is not None and all_in is not None) else None

    numbers = {opened_at: i + 1 for i, opened_at in enumerate(sorted(entries))}
    markers: list[dict[str, Any]] = []

    for opened_at, e in entries.items():
        arms = sorted(e["arms"], key=lambda a: a["width"])
        markers.append(
            {
                "n": numbers[opened_at],
                "kind": "entry",
                "dir": "bull" if e["direction"] == "BULLISH" else "bear",
                "time": to_epoch(opened_at),
                "price": e.get("entry_spot"),
                "legs": [
                    {
                        "arm": ARM_NAMES[a["variant"]],
                        "spread": spread_text(a),
                        "credit": round2(a["entry_credit"]),
                    }
                    for a in arms
                ],
            }
        )

    for (opened_at, closed_at), group in closes.items():
        group.sort(key=lambda a: a["width"])
        reason = str(group[0].get("close_reason") or "")
        markers.append(
            {
                "n": numbers.get(opened_at, 0),
                "kind": "close",
                "time": to_epoch(closed_at),
                "price": None,
                "reason": CLOSE_REASONS.get(reason, reason.replace("_", " ")),
                "legs": [
                    {
                        "arm": ARM_NAMES[a["variant"]],
                        "spread": spread_text(a),
                        "credit": round2(a["entry_credit"]),
                        "cost": round2(a["close_cost"]),
                        "net": net_of(opened_at, a["variant"]),
                    }
                    for a in group
                    if a.get("close_cost") is not None
                ],
            }
        )

    for e in completions:
        K, w = e["short_strike"], e["width"]
        credit = e["entry_credit"] + e["completion_credit"]
        markers.append(
            {
                "n": numbers.get(e["opened_at"], 0),
                "kind": "fly",
                "time": to_epoch(e["completed_at"]),
                "price": e.get("completion_spot"),
                "arm": ARM_NAMES[e["variant"]],
                "strikes": [K - w, K, K + w],
                "credit": round2(credit),
                "lossless": credit >= w,
                "breakEvens": fly_break_evens(K, w, credit),
                "net": net_of(e["opened_at"], e["variant"]),
            }
        )

    for opened_at, e in eod.items():
        K, w = e["short_strike"], e["width"]
        debit = -e["entry_credit"]
        markers.append(
            {
                "n": len(numbers) + 1,
                "kind": "eod_fly",
                "time": to_epoch(opened_at),
                "price": e.get("entry_spot"),
                "arm": f"w{w:g}",
                "strikes": [K - w, K, K + w],
                "debit": round2(debit),
                "breakEvens": long_fly_break_evens(K, w, debit),
                "net": net_of(opened_at, EOD_FLY_VARIANT),
            }
        )

    return sorted(markers, key=lambda m: (m["time"], m["n"]))
