"""End-of-day analysis for a TT-156 research day.

Reads the captured chain snapshots, simulator events, and final results,
and writes REPORT.md with:

1. Day overview — spot path, signal counts.
2. Live paper-trading results per variant.
3. Retro-sweep — signal-agnostic grid over (entry time × direction × width):
   for every 5-minute entry point, would the butterfly have completed?
   This separates "the structure can work" from "the signal timed it well".

Usage:
    uv run python -m research.tt156_zero_dte_butterfly.report research_data/TT-156/<date>
"""

import argparse
import gzip
import json
from datetime import datetime, time
from pathlib import Path

from research.tt156_zero_dte_butterfly.config import (
    CONTRACT_MULTIPLIER,
    ET,
    FORCED_CLOSE,
    LAST_COMPLETION,
    STRIKE_STEP,
)

SWEEP_WIDTHS = (10.0, 25.0, 50.0, 75.0)
SWEEP_ENTRY_START = time(9, 45)
SWEEP_ENTRY_END = time(14, 30)
SWEEP_GRID_MINUTES = 5


def load_snapshots(data_dir: Path) -> list[dict]:
    path = data_dir / "chain_snapshots.jsonl.gz"
    snapshots: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            snapshots.append(json.loads(line))
    return snapshots


def snapshot_quotes(snapshot: dict) -> dict[tuple[float, str], dict]:
    return {(opt["strike"], opt["cp"]): opt for opt in snapshot["options"]}


def mid(quotes: dict, strike: float, cp: str) -> float | None:
    quote = quotes.get((strike, cp))
    if quote is None:
        return None
    ask = quote.get("ask")
    if ask is None or ask <= 0:
        return None
    return ((quote.get("bid") or 0.0) + ask) / 2


def vertical(quotes: dict, short: float, long: float, cp: str) -> float | None:
    short_mid, long_mid = mid(quotes, short, cp), mid(quotes, long, cp)
    if short_mid is None or long_mid is None:
        return None
    return short_mid - long_mid


def entry_credit(
    quotes: dict, direction: str, strike: float, width: float
) -> float | None:
    if direction == "BEARISH":
        return vertical(quotes, strike, strike + width, "C")
    return vertical(quotes, strike, strike - width, "P")


def counter_credit(
    quotes: dict, direction: str, strike: float, width: float
) -> float | None:
    if direction == "BEARISH":
        return vertical(quotes, strike, strike - width, "P")
    return vertical(quotes, strike, strike + width, "C")


def snapshot_et(snapshot: dict) -> datetime:
    return datetime.fromisoformat(snapshot["ts"]).astimezone(ET)


def retro_sweep(snapshots: list[dict]) -> list[dict]:
    """For each (entry time, direction, width): trace the rest of the day."""
    results: list[dict] = []
    grid: list[int] = []
    last_bucket = -1
    for idx, snap in enumerate(snapshots):
        ts = snapshot_et(snap)
        if not (SWEEP_ENTRY_START <= ts.time() <= SWEEP_ENTRY_END):
            continue
        bucket = ts.hour * 60 + ts.minute - (ts.minute % SWEEP_GRID_MINUTES)
        if bucket != last_bucket:
            grid.append(idx)
            last_bucket = bucket

    for idx in grid:
        snap = snapshots[idx]
        ts = snapshot_et(snap)
        quotes = snapshot_quotes(snap)
        spot = snap["spot"]
        strike = round(spot / STRIKE_STEP) * STRIKE_STEP
        for direction in ("BEARISH", "BULLISH"):
            for width in SWEEP_WIDTHS:
                credit = entry_credit(quotes, direction, strike, width)
                if credit is None or credit <= 0:
                    continue
                outcome = trace_outcome(
                    snapshots, idx, direction, strike, width, credit
                )
                results.append(
                    {
                        "entry_time": ts.isoformat(),
                        "direction": direction,
                        "strike": strike,
                        "width": width,
                        "entry_credit": credit,
                        "entry_spot": spot,
                        **outcome,
                    }
                )
    return results


def trace_outcome(
    snapshots: list[dict],
    entry_idx: int,
    direction: str,
    strike: float,
    width: float,
    credit: float,
    margin: float = 0.0,
) -> dict:
    """Walk forward: complete at threshold, else forced close at 15:45."""
    for snap in snapshots[entry_idx + 1 :]:
        ts = snapshot_et(snap)
        quotes = snapshot_quotes(snap)
        if ts.time() <= LAST_COMPLETION:
            counter = counter_credit(quotes, direction, strike, width)
            if counter is not None and credit + counter >= width + margin:
                return {
                    "completed": True,
                    "completion_time": ts.isoformat(),
                    "minutes_to_complete": (
                        ts - snapshot_et(snapshots[entry_idx])
                    ).total_seconds()
                    / 60,
                    "locked_min_pnl": credit + counter - width,
                    "spot_move": snap["spot"] - snapshots[entry_idx]["spot"],
                }
        if ts.time() >= FORCED_CLOSE:
            cost = entry_credit(quotes, direction, strike, width)
            pnl = credit - cost if cost is not None else None
            return {
                "completed": False,
                "close_pnl": pnl,
                "spot_move": snap["spot"] - snapshots[entry_idx]["spot"],
            }
    return {"completed": False, "close_pnl": None, "spot_move": None}


def fmt_pts(value: float | None) -> str:
    if value is None:
        return "n/a"
    dollars = value * CONTRACT_MULTIPLIER
    usd = f"-${abs(dollars):,.0f}" if dollars < 0 else f"${dollars:,.0f}"
    return f"{value:.2f} pts ({usd})"


def reconstruct_structures(
    data_dir: Path, snapshots: list[dict], settle_spot: float
) -> list[dict]:
    """Rebuild every structure of the day from events.jsonl.

    The simulator's final_results.json only covers the last process; the
    event log spans restarts. Structures keyed by (variant, direction,
    opened_at). Completed-but-unsettled flies are settled here from their
    recorded credits; entries orphaned by a restart are traced forward
    through the snapshot file under the live rules (complete at threshold,
    else forced close at 15:45).
    """
    structures: dict[tuple, dict] = {}
    for line in (data_dir / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        key = (e["variant"], e["direction"], e["opened_at"])
        if e["event"] == "ENTRY":
            structures[key] = {**e, "outcome": "open"}
        elif key in structures:
            s = structures[key]
            if e["event"] == "COMPLETION":
                s.update(e)
                s["outcome"] = "completed"
            elif e["event"] == "CLOSE":
                s.update(e)
                s["outcome"] = "closed"
            elif e["event"] == "SETTLEMENT":
                s.update(e)
                s["outcome"] = "settled"

    times = [snapshot_et(s) for s in snapshots]
    for s in structures.values():
        if s["outcome"] == "completed":
            total = s["entry_credit"] + s["completion_credit"]
            s["pnl_points"] = total - min(
                abs(settle_spot - s["short_strike"]), s["width"]
            )
            s["outcome"] = "settled"
        elif s["outcome"] == "open":
            # Orphaned by a collector restart. No backdated fills: flips are
            # only detectable at snapshots, which only exist while a collector
            # was alive — so the exit prices at recovery, never inside a gap.
            # Replay the live rules from
            # (good-faith estimate of unbroken behavior), else 15:45 close.
            opened = datetime.fromisoformat(s["opened_at"]).astimezone(ET)
            idx = next((i for i, t in enumerate(times) if t >= opened), None)
            if idx is None:
                continue
            margin = 2.0 if s["variant"].endswith("m2") else 0.0
            s["orphaned"] = True
            flip_idx = first_engine_flip(snapshots, idx, s)
            trace_end = flip_idx if flip_idx is not None else len(snapshots)
            traced = trace_outcome(
                snapshots[:trace_end] if flip_idx is not None else snapshots,
                idx,
                s["direction"],
                s["short_strike"],
                s["width"],
                s["entry_credit"],
                margin,
            )
            if traced["completed"]:
                total = s["entry_credit"] + traced.get(
                    "completion_credit", s["width"] + margin - s["entry_credit"]
                )
                s["completion_credit"] = total - s["entry_credit"]
                s["completed_at"] = traced["completion_time"]
                s["pnl_points"] = total - min(
                    abs(settle_spot - s["short_strike"]), s["width"]
                )
                s["outcome"] = "settled"
            elif flip_idx is not None:
                quotes = snapshot_quotes(snapshots[flip_idx])
                cost = entry_credit(
                    quotes, s["direction"], s["short_strike"], s["width"]
                )
                s["pnl_points"] = s["entry_credit"] - cost if cost is not None else None
                s["closed_at"] = snapshots[flip_idx]["ts"]
                s["close_reason"] = "orphan_engine_flip"
                s["outcome"] = "closed"
            else:
                s["pnl_points"] = traced.get("close_pnl")
                s["outcome"] = "closed"
    return list(structures.values())


def first_engine_flip(snapshots: list[dict], entry_idx: int, s: dict) -> int | None:
    """Index of the first snapshot whose recorded engine state opposes the
    structure's direction — when the live opposing-signal close would fire."""
    interval = "5m" if "5m" in s["variant"] else "m"
    key = f"SPX{{={interval}}}"
    for i in range(entry_idx + 1, len(snapshots)):
        eng = snapshots[i].get("engine", {}).get(key)
        if not eng:
            continue
        hull, macd = eng.get("hull_direction"), eng.get("macd_position")
        if s["direction"] == "BEARISH" and (hull == "Up" or macd == "bullish"):
            return i
        if s["direction"] == "BULLISH" and (hull == "Down" or macd == "bearish"):
            return i
    return None


def risk_and_whipsaw_lines(data_dir: Path, reconstructed: list[dict]) -> list[str]:
    """Peak outstanding risk and sub-2-minute whipsaw stats from the event log."""
    whipsaws = [
        s
        for s in reconstructed
        if s["outcome"] == "closed"
        and s.get("closed_at")
        and (
            datetime.fromisoformat(s["closed_at"])
            - datetime.fromisoformat(s["opened_at"])
        ).total_seconds()
        < 120
    ]
    peak_risk = 0.0
    running: dict[tuple, float] = {}
    events = sorted(
        (
            json.loads(line)
            for line in (data_dir / "events.jsonl").read_text().splitlines()
        ),
        key=lambda e: e["ts"],
    )
    for e in events:
        key = (e["variant"], e["direction"], e["opened_at"])
        if e["event"] == "ENTRY":
            running[key] = e["width"] - e["entry_credit"]
        else:
            running.pop(key, None)
        peak_risk = max(peak_risk, sum(running.values()))
    return [
        f"Whipsaw round trips (< 2 min): {len(whipsaws)}, net "
        f"{fmt_pts(sum(s['pnl_points'] or 0.0 for s in whipsaws))}",
        f"Peak outstanding risk (whole 12-variant grid): {peak_risk:.2f} pts "
        f"(${peak_risk * CONTRACT_MULTIPLIER:,.0f})",
    ]


def exit_policy_section(reconstructed: list[dict], snapshots: list[dict]) -> list[str]:
    """Hold-to-settle vs mid-day unwind values for every locked butterfly."""
    lines = [
        "## Exit-policy comparison for locked butterflies",
        "",
        "Hold-to-settle is the live rule; unwind columns show what buying back "
        "both verticals at mid would have realized instead.",
        "",
        "| Fly | Hold to settle | Best unwind (mid) | Unwind +30min after lock |",
        "|---|---|---|---|",
    ]
    for s in reconstructed:
        if s.get("completion_credit") is None or not s.get("completed_at"):
            continue
        total = s["entry_credit"] + s["completion_credit"]
        completed_at = datetime.fromisoformat(s["completed_at"]).astimezone(ET)
        unwinds: list[float] = []
        unwind_30 = None
        for snap in snapshots:
            t = snapshot_et(snap)
            if t <= completed_at:
                continue
            quotes = snapshot_quotes(snap)
            call_cost = vertical(
                quotes, s["short_strike"], s["short_strike"] + s["width"], "C"
            )
            put_cost = vertical(
                quotes, s["short_strike"], s["short_strike"] - s["width"], "P"
            )
            if call_cost is None or put_cost is None:
                continue
            value = total - (call_cost + put_cost)
            unwinds.append(value)
            if unwind_30 is None and (t - completed_at).total_seconds() >= 1800:
                unwind_30 = value
        lines.append(
            f"| {s['variant']} K={s['short_strike']:g} | "
            f"{fmt_pts(s.get('pnl_points'))} | "
            f"{fmt_pts(max(unwinds) if unwinds else None)} | {fmt_pts(unwind_30)} |"
        )
    lines.append("")
    return lines


# Canonical all-in cost model (user-calibrated), charged per SPREAD ORDER
# (one 2-option vertical executed as a complex order):
# - fill concession: the spread fills at mid plus a fixed concession
#   (bounds for sensitivity)
# - commissions + exchange/regulatory fees: ~$1/option x2 plus exchange
#   fees, ~$5 total per spread order
# - settlement: $5 per option finishing ITM (auto-exercise/assignment);
#   OTM options expire free
FILL_COST_PER_SPREAD = 0.075
FILL_COST_BOUNDS = (0.05, 0.10)
FEES_PER_SPREAD = 0.05  # $5/spread commission + exchange fees, in SPX points
SETTLEMENT_FEE_PER_ITM_LEG = 0.05  # $5/option exercise/assignment


def legs_filled(s: dict) -> int:
    legs = len(s.get("entry_legs") or [])
    legs += len(s.get("completion_legs") or [])
    if s["outcome"] == "closed":
        legs += len(s.get("entry_legs") or [])  # exit crosses the same legs
    return legs


def itm_legs_at_settlement(s: dict, settle_spot: float) -> int:
    """Count fly legs finishing ITM (assessed exercise/assignment fees)."""
    if s["outcome"] != "settled" or s.get("completion_credit") is None:
        return 0
    K, w = s["short_strike"], s["width"]
    count = 0
    for strike in (K, K + w):  # call legs
        if settle_spot > strike:
            count += 1
    for strike in (K, K - w):  # put legs
        if settle_spot < strike:
            count += 1
    return count


def usd(value: float) -> str:
    """Dollars, no plus sign on positives: $1,234 / -$1,234."""
    d = value * 100
    return f"-${abs(d):,.0f}" if d < 0 else f"${d:,.0f}"


def time_bucket(opened_at: str) -> int:
    """0=morning (<11:30 ET), 1=midday (11:30-13:30), 2=afternoon (>13:30)."""
    t = datetime.fromisoformat(opened_at)  # collector writes ET-local timestamps
    m = t.hour * 60 + t.minute
    return 0 if m < 11 * 60 + 30 else (1 if m < 13 * 60 + 30 else 2)


def cell_all_in(rows: list[dict], settle_spot: float) -> float:
    """All-in P&L (points) for a set of structures, canonical cost model."""
    pnl_mid = sum(s["pnl_points"] or 0.0 for s in rows)
    spreads = sum(legs_filled(s) for s in rows) // 2
    itm = sum(itm_legs_at_settlement(s, settle_spot) for s in rows)
    per_spread = FILL_COST_PER_SPREAD + FEES_PER_SPREAD
    return pnl_mid - spreads * per_spread - itm * SETTLEMENT_FEE_PER_ITM_LEG


def tranche_timeframe_block(reconstructed: list[dict], settle_spot: float) -> list[str]:
    """Lead block: all-in P&L decomposed by config tranche AND time of day.

    The lumped grid total is deliberately NOT the headline — it averages
    red-herring configs together and is not actionable. Read the tranches.
    """
    groups: list[tuple[str, object]] = [
        ("1m signal", lambda v: "_m_" in v),
        ("5m signal", lambda v: "_5m_" in v),
        ("w10", lambda v: v.startswith("w10")),
        ("w25", lambda v: v.startswith("w25")),
        ("w50", lambda v: v.startswith("w50")),
    ]

    def cell(pred: object, b: int) -> float:
        rows = [
            s
            for s in reconstructed
            if pred(s["variant"]) and time_bucket(s["opened_at"]) == b  # type: ignore[operator]
        ]
        return cell_all_in(rows, settle_spot)

    lines = [
        "## All-in P&L by tranche x time of day",
        "",
        "Read the tranches, not a lumped total — it averages red-herring "
        "configs together. Each partition (by signal, by width) sums across "
        "time to its row total and down each column to the column total.",
        "",
        "| Tranche | Morning | Midday | Afternoon | Total |",
        "|---|---|---|---|---|",
    ]
    col = [0.0, 0.0, 0.0]
    for label, pred in groups:
        cells = [cell(pred, b) for b in range(3)]
        if label == "w10":  # widths partition the grid too; separate visually
            lines.append("| *— by width —* | | | | |")
        if label in ("1m signal", "5m signal"):
            for i in range(3):
                col[i] += cells[i]
        row = " | ".join(usd(c) for c in cells)
        lines.append(f"| {label} | {row} | {usd(sum(cells))} |")
    lines.append(
        f"| **All time** | {usd(col[0])} | {usd(col[1])} | {usd(col[2])} | "
        f"{usd(sum(col))} |"
    )

    best = max(reconstructed, key=lambda s: s.get("pnl_points") or 0.0)
    worst = min(reconstructed, key=lambda s: s.get("pnl_points") or 0.0)
    pnl_mid = sum(s["pnl_points"] or 0.0 for s in reconstructed)
    spreads = sum(legs_filled(s) for s in reconstructed) // 2
    lines += [
        "",
        f"Gross at mid {fmt_pts(pnl_mid)} across {spreads} spread orders "
        f"(friction {fmt_pts(-spreads * (FILL_COST_PER_SPREAD + FEES_PER_SPREAD))}). "
        f"Best structure {best['variant']} {best['direction']} "
        f"K={best['short_strike']:g}: {fmt_pts(best.get('pnl_points'))}; "
        f"worst {worst['variant']} {worst['direction']} "
        f"K={worst['short_strike']:g}: {fmt_pts(worst.get('pnl_points'))}.",
        "",
    ]
    return lines


def rollup_block(reconstructed: list[dict], settle_spot: float) -> list[str]:
    """Headline P&L rollup — the one-glance answer, before any slicing."""
    pnl_mid = sum(s["pnl_points"] or 0.0 for s in reconstructed)
    total_legs = sum(legs_filled(s) for s in reconstructed)
    spreads = total_legs // 2  # 2 options per spread order
    itm_legs = sum(itm_legs_at_settlement(s, settle_spot) for s in reconstructed)
    settle_fees = itm_legs * SETTLEMENT_FEE_PER_ITM_LEG
    per_spread = FILL_COST_PER_SPREAD + FEES_PER_SPREAD
    realistic = pnl_mid - spreads * per_spread - settle_fees
    lo = pnl_mid - spreads * (FILL_COST_BOUNDS[1] + FEES_PER_SPREAD) - settle_fees
    hi = pnl_mid - spreads * (FILL_COST_BOUNDS[0] + FEES_PER_SPREAD) - settle_fees

    settled = [s for s in reconstructed if s["outcome"] == "settled"]
    closed = [s for s in reconstructed if s["outcome"] == "closed"]
    realized = sum(s["pnl_points"] or 0.0 for s in closed)
    fly_pnl = sum(s["pnl_points"] or 0.0 for s in settled)
    whips = [
        s
        for s in closed
        if s.get("closed_at")
        and (
            datetime.fromisoformat(s["closed_at"])
            - datetime.fromisoformat(s["opened_at"])
        ).total_seconds()
        < 120
    ]
    best = max(reconstructed, key=lambda s: s.get("pnl_points") or 0.0)
    worst = min(reconstructed, key=lambda s: s.get("pnl_points") or 0.0)
    return [
        "## P&L rollup (the whole day in one block)",
        "",
        "| | |",
        "|---|---|",
        f"| **Day P&L at mid fills** | **{fmt_pts(pnl_mid)}** |",
        f"| **Day P&L all-in** (concession {FILL_COST_PER_SPREAD} + fees "
        f"{FEES_PER_SPREAD} per spread order + settlement) | "
        f"**{fmt_pts(realistic)}** (range {fmt_pts(lo)} to {fmt_pts(hi)} at "
        f"+{FILL_COST_BOUNDS[0]}/+{FILL_COST_BOUNDS[1]} concession) |",
        f"| from closed verticals (realized) | {fmt_pts(realized)} ({len(closed)} trades) |",
        f"| from settled butterflies | {fmt_pts(fly_pnl)} ({len(settled)} flies) |",
        f"| concession + fees ({spreads} spread orders) | "
        f"{fmt_pts(-spreads * per_spread)} |",
        f"| settlement fees ({itm_legs} ITM legs x $5) | {fmt_pts(-settle_fees)} |",
        f"| whipsaw round trips (<2 min) | {len(whips)}, "
        f"{fmt_pts(sum(s['pnl_points'] or 0.0 for s in whips))} at mid |",
        f"| best single structure | {best['variant']} {best['direction']} "
        f"K={best['short_strike']:g}: {fmt_pts(best.get('pnl_points'))} |",
        f"| worst single structure | {worst['variant']} {worst['direction']} "
        f"K={worst['short_strike']:g}: {fmt_pts(worst.get('pnl_points'))} |",
        "",
    ]


def variant_table(reconstructed: list[dict], variants: list[str]) -> list[str]:
    lines = [
        "| Variant | Entries | Completed | Closed early | P&L |",
        "|---|---|---|---|---|",
    ]
    for name in variants:
        rows = [s for s in reconstructed if s["variant"] == name]
        completed = [s for s in rows if s.get("completion_credit") is not None]
        closed = [s for s in rows if s["outcome"] == "closed"]
        pnl = sum(s["pnl_points"] or 0.0 for s in rows)
        lines.append(
            f"| {name} | {len(rows)} | {len(completed)} | "
            f"{len(closed)} | {fmt_pts(pnl)} |"
        )
    return lines


def build_report(data_dir: Path) -> str:
    header = json.loads((data_dir / "header.json").read_text())
    results_path = data_dir / "final_results.json"
    # Absent until a collector instance finishes cleanly; reconstruction
    # below does not depend on it.
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    snapshots = load_snapshots(data_dir)

    spots = [s["spot"] for s in snapshots]
    lines = [
        f"# TT-156 Research Day — {header['date']}",
        "",
        f"SPX: open {spots[0]:.0f} → high {max(spots):.0f} / low {min(spots):.0f} "
        f"→ settled {results.get('settlement_spot') or spots[-1]} "
        f"(prior close {header['index_summary'].get('prev_close')}). "
        f"{len(snapshots)} chain snapshots at {header['cadence_seconds']:.0f}s cadence.",
        "",
    ]
    narrative = data_dir / "narrative.md"
    if narrative.exists():
        lines += ["## The day's story", "", narrative.read_text().strip(), ""]
    settle_value = results.get("settlement_spot")
    if settle_value is None:
        settle_value = next(
            (
                s["spot"]
                for s in reversed(snapshots)
                if snapshot_et(s).time() <= time(16, 0, 30)
            ),
            spots[-1],
        )
    assert settle_value is not None  # spots is non-empty, so the fallback exists
    settle_spot = float(settle_value)
    reconstructed = reconstruct_structures(data_dir, snapshots, settle_spot)
    variant_names = [v["name"] for v in header["variants"]]
    lines += tranche_timeframe_block(reconstructed, settle_spot)
    orphans = [s for s in reconstructed if s.get("orphaned")]
    lines += [
        "## Per-variant slice (mid fills)",
        "",
        "Reconstructed from events.jsonl across all collector instances; "
        "restart-orphaned structures exit at the first post-recovery snapshot "
        "(no backdated fills).",
        "",
        *variant_table(reconstructed, variant_names),
        "",
        f"Structures reconstructed: {len(reconstructed)} "
        f"({len(orphans)} orphaned by restarts)",
        f"Skipped entries (unusable quotes, last instance): {results.get('skipped_entries', 0)}",
        *risk_and_whipsaw_lines(data_dir, reconstructed),
        "",
        *exit_policy_section(reconstructed, snapshots),
        "## Retro-sweep — every 5-min entry, both directions, widths "
        f"{', '.join(str(int(w)) for w in SWEEP_WIDTHS)}",
        "",
    ]

    sweep = retro_sweep(snapshots)
    if sweep:
        lines += [
            "| Width | Trials | Completed | Completion % | Avg min-to-complete | Avg locked P&L | Avg loss when failed |",
            "|---|---|---|---|---|---|---|",
        ]
        for width in SWEEP_WIDTHS:
            rows = [r for r in sweep if r["width"] == width]
            done = [r for r in rows if r["completed"]]
            failed = [
                r for r in rows if not r["completed"] and r.get("close_pnl") is not None
            ]
            if not rows:
                continue
            avg_minutes = (
                sum(r["minutes_to_complete"] for r in done) / len(done)
                if done
                else None
            )
            avg_locked = (
                sum(r["locked_min_pnl"] for r in done) / len(done) if done else None
            )
            avg_loss = (
                sum(r["close_pnl"] for r in failed) / len(failed) if failed else None
            )
            lines.append(
                f"| {width:g} | {len(rows)} | {len(done)} | "
                f"{100 * len(done) / len(rows):.1f}% | "
                + (f"{avg_minutes:.0f}" if avg_minutes is not None else "n/a")
                + " | "
                + (fmt_pts(avg_locked) if avg_locked is not None else "n/a")
                + " | "
                + (fmt_pts(avg_loss) if avg_loss is not None else "n/a")
                + " |"
            )
        sweep_path = data_dir / "retro_sweep.json"
        sweep_path.write_text(json.dumps(sweep, indent=2, default=str))
        lines += ["", f"Full sweep data: {sweep_path.name} ({len(sweep)} trials)"]
    else:
        lines.append("No sweep trials produced (insufficient snapshots).")

    lines += [
        "",
        "## Caveats",
        "",
        "- Single session. Slice tables are at mid fills; the rollup's all-in "
        "line carries the canonical cost model (per-spread concession + fees "
        "+ settlement).",
        "- Completion threshold uses mid credit — real fills at the threshold "
        "would need the market to trade through, so live completion rates "
        "would be lower.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="TT-156 EOD report")
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    report = build_report(args.data_dir)
    out = args.data_dir / "REPORT.md"
    out.write_text(report)
    print(f"Report written to {out}")


if __name__ == "__main__":
    main()
