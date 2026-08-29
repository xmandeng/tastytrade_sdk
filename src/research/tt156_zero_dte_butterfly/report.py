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
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from research.tt156_zero_dte_butterfly import regime
from research.tt156_zero_dte_butterfly.gate import GATED_BUCKETS
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


def load_events(data_dir: Path) -> list[dict]:
    """Read events.jsonl, tolerating its absence on a no-trade day.

    The collector only writes events.jsonl once a structure exists, so a
    session that never fires (out-of-scope regime — see the regime-selectivity
    note) has no file. That is a valid outcome, not an error.
    """
    path = data_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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
    for e in load_events(data_dir):
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
            margin = 2.0 if "_m2" in s["variant"] else 0.0
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
    peak: dict[str, float] = {"atm": 0.0, "hw": 0.0}
    running: dict[tuple, float] = {}
    events = sorted(load_events(data_dir), key=lambda e: e["ts"])
    for e in events:
        key = (e["variant"], e["direction"], e["opened_at"])
        if e["event"] == "ENTRY":
            running[key] = e["width"] - e["entry_credit"]
        else:
            running.pop(key, None)
        for arm in peak:
            peak[arm] = max(
                peak[arm],
                sum(risk for k, risk in running.items() if arm_of(k[0]) == arm),
            )
    lines = [
        f"Whipsaw round trips (< 2 min): {len(whipsaws)}, net "
        f"{fmt_pts(sum(s['pnl_points'] or 0.0 for s in whipsaws))}"
    ]
    if peak["hw"] > 0:
        for arm, label in (("atm", "ATM arm"), ("hw", "half-width arm")):
            lines.append(
                f"Peak outstanding risk ({label}): {peak[arm]:.2f} pts "
                f"(${peak[arm] * CONTRACT_MULTIPLIER:,.0f})"
            )
    else:
        lines.append(
            f"Peak outstanding risk (whole 12-variant grid): {peak['atm']:.2f} pts "
            f"(${peak['atm'] * CONTRACT_MULTIPLIER:,.0f})"
        )
    return lines


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


def signal_of(variant: str) -> str:
    return "5m" if "_5m_" in variant else "1m"


def width_of(variant: str) -> str:
    return variant.split("_", 1)[0]


def arm_of(variant: str) -> str:
    """Arm: "ghw" (gate-enforced half-width), "hw" (half-width), or "atm"."""
    if variant.endswith("_ghw"):
        return "ghw"
    return "hw" if variant.endswith("_hw") else "atm"


ARM_LABELS = {
    "atm": "ATM arm",
    "hw": "Half-width arm (entry credit > w/2)",
    "ghw": "Gate-enforced arm (imminent/near clusters only, entry credit > w/2)",
}
ARMS = ("atm", "hw", "ghw")


def tranche_timeframe_block(reconstructed: list[dict], settle_spot: float) -> list[str]:
    """Lead block: all-in P&L by (signal x width) family x time of day.

    Rows are DISJOINT (signal x width) families — they partition the grid. Each
    row shows its own tranche total across time; there is deliberately NO lumped
    total (no Total row, no grand total). The grid is a research instrument to
    find WHICH tranche has edge, not a portfolio meant to be net-profitable
    across all 12 variants, so a summed all-in number implies an objective the
    experiment does not have. The block instead calls out the winning tranche.
    """
    lines = [
        "## P&L by signal x width family x time of day (all-in cost model)",
        "",
        "Disjoint families (no overlap). This grid is a research instrument to "
        "find WHICH tranche has edge — not a portfolio meant to be net-profitable "
        "across all variants. There is deliberately NO lumped all-in total "
        "(neither a Total row nor a grand total): summing intentionally-diverse "
        "configs implies an objective the experiment does not have. Read the "
        "families; the winning tranche is called out below. The ATM and "
        "half-width strike arms are reported separately and never summed.",
        "",
    ]
    arms = [
        (arm, [s for s in reconstructed if arm_of(s["variant"]) == arm]) for arm in ARMS
    ]
    arms = [(arm, rows) for arm, rows in arms if rows]
    for arm, arm_rows in arms:
        if len(arms) > 1:
            lines += [f"### {ARM_LABELS[arm]}", ""]
        lines += family_table(arm_rows, settle_spot)
        if arm in ("hw", "ghw"):
            lines += halfwidth_entry_diagnostics(arm_rows)
    return lines


def family_table(rows: list[dict], settle_spot: float) -> list[str]:
    """Family × time-of-day table with winning-tranche callout for one arm."""
    families = sorted(
        {(signal_of(s["variant"]), width_of(s["variant"])) for s in rows},
        key=lambda f: (f[0], int(f[1][1:])),
    )

    def cell(sig: str, wid: str, b: int) -> float:
        sub = [
            s
            for s in rows
            if signal_of(s["variant"]) == sig
            and width_of(s["variant"]) == wid
            and time_bucket(s["opened_at"]) == b
        ]
        return cell_all_in(sub, settle_spot)

    lines = [
        "| Family | Morning | Midday | Afternoon | Tranche total |",
        "|---|---|---|---|---|",
    ]
    fam_totals: dict[str, float] = {}
    for sig, wid in families:
        cells = [cell(sig, wid, b) for b in range(3)]
        fam_totals[f"{sig}·{wid}"] = sum(cells)
        row = " | ".join(usd(c) for c in cells)
        lines.append(f"| {sig}·{wid} | {row} | {usd(sum(cells))} |")

    # Surface the winning tranche, never a lumped total.
    best_fam = max(fam_totals, key=lambda k: fam_totals[k])
    best = max(rows, key=lambda s: s.get("pnl_points") or 0.0)
    worst = min(rows, key=lambda s: s.get("pnl_points") or 0.0)
    spreads = sum(legs_filled(s) for s in rows) // 2
    lines += [
        "",
        f"**Most successful tranche: {best_fam} {usd(fam_totals[best_fam])}.** "
        f"Best single structure {best['variant']} {best['direction']} "
        f"K={best['short_strike']:g}: {fmt_pts(best.get('pnl_points'))}; "
        f"worst {worst['variant']} {worst['direction']} "
        f"K={worst['short_strike']:g}: {fmt_pts(worst.get('pnl_points'))}. "
        f"{spreads} spread orders, friction "
        f"{fmt_pts(-spreads * (FILL_COST_PER_SPREAD + FEES_PER_SPREAD))}.",
        "",
    ]
    return lines


def halfwidth_entry_diagnostics(hw_rows: list[dict]) -> list[str]:
    """Achieved credit fraction / ITM depth for half-width entries — verifies
    the strike rule is behaving live."""
    fracs = sorted(s["entry_credit"] / s["width"] for s in hw_rows)
    depths = sorted(
        abs(s["short_strike"] - round(s["entry_spot"] / STRIKE_STEP) * STRIKE_STEP)
        for s in hw_rows
    )
    return [
        f"Half-width entries: {len(hw_rows)}; credit fraction median "
        f"{fracs[len(fracs) // 2]:.1%} (min {fracs[0]:.1%}, max {fracs[-1]:.1%}); "
        f"ITM depth vs ATM median {depths[len(depths) // 2]:g} pts "
        f"(max {depths[-1]:g}).",
        "",
    ]


def regime_read_block(snapshots: list[dict], data_dir: Path) -> list[str]:
    """Prospective trend-day odds from data observable by 11:00 ET only.

    Rendered on every session (including no-trade days) so the regime call
    accumulates alongside the gate scoreboard with the same discipline: the
    inputs are frozen at 11:00, the calibration is frozen constants.
    """
    lines = ["## Regime read @ 11:00 (prospective)", ""]
    spot_path = []
    macd_positions = []
    for s in snapshots:
        t = snapshot_et(s)
        m = t.hour * 60 + t.minute
        if m >= regime.MORNING_END_MINUTE:
            continue
        spot_path.append((m, s["spot"]))
        pos = (s.get("engine") or {}).get("SPX{=5m}", {}).get("macd_position")
        if pos:
            macd_positions.append(pos)

    atr = regime.trailing_atr(data_dir)
    feats = regime.morning_features(spot_path, atr)
    if feats is None:
        return lines + ["insufficient morning data for a regime read", ""]

    call = regime.trend_call(feats)
    drive_txt = (
        "n/a (fewer than 5 prior sessions for ATR)"
        if feats.drive_atr is None
        else f"{feats.drive_atr:.2f}x ATR20"
    )
    one_sided = (
        max(macd_positions.count("bullish"), macd_positions.count("bearish"))
        / len(macd_positions)
        if macd_positions
        else None
    )
    lines += [
        f"- Opening drive (9:30-11:00): {feats.net_pts:+.1f} pts = {drive_txt} "
        f"(Q25 {regime.DRIVE_Q25:.2f} / Q75 {regime.DRIVE_Q75:.2f})",
        f"- Deepest morning retrace: {feats.retrace_frac:.2f}x the net move "
        f"(Q25 {regime.RETRACE_Q25:.2f} / Q75 {regime.RETRACE_Q75:.2f})",
    ]
    if one_sided is not None:
        lines.append(
            f"- 5m MACD one-sidedness through 11:00: {one_sided:.0%} of cycles "
            f"in the modal position"
        )
    if call is None:
        lines += ["", "No trend call — trailing ATR unavailable.", ""]
    else:
        label, prob = call
        lines += [
            "",
            f"**Call: {label} — P(trend day) ≈ {prob:.0%}** (base rate 29%; "
            f"calibrated on 377 sessions, frozen 2026-08-12). The read is "
            f"asymmetric by construction: weak-drive/deep-retrace mornings "
            f"exclude trend days far more reliably than strong mornings "
            f"predict them.",
            "",
        ]
    return lines


def gate_cluster_key(s: dict) -> tuple:
    return (s["opened_at"], s["direction"])


def events_only_day(day_dir: Path) -> tuple[list[dict], int, float | None]:
    """Lightweight per-day reconstruction for the cumulative gate scoreboard.

    Events only — no snapshot replay, so restart-orphaned entries (outcome
    still open in the log) are skipped and counted rather than traced. The
    per-day report tables remain the authoritative accounting; this powers
    the running gated-vs-ungated comparison across sessions.
    """
    structures: dict[tuple, dict] = {}
    settle_spot: float | None = None
    for e in load_events(day_dir):
        key = (e["variant"], e["direction"], e["opened_at"])
        structures.setdefault(key, {}).update(e)
        if e.get("settlement_spot") is not None:
            settle_spot = e["settlement_spot"]
    rows, skipped = [], 0
    for s in structures.values():
        status = str(s.get("status") or "")
        s["outcome"] = {"CLOSED": "closed", "SETTLED": "settled"}.get(status, "open")
        if s["outcome"] == "open" and s.get("completion_credit") and settle_spot:
            total = s["entry_credit"] + s["completion_credit"]
            s["pnl_points"] = total - min(
                abs(settle_spot - s["short_strike"]), s["width"]
            )
            s["outcome"] = "settled"
        if s.get("pnl_points") is None:
            skipped += 1
            continue
        rows.append(s)
    return rows, skipped, settle_spot


def gate_width_cells(rows: list[dict], settle_spot: float, arm: str = "atm") -> str:
    cells = []
    for wid in ("w10", "w25", "w50"):
        sub = [
            s
            for s in rows
            if width_of(s["variant"]) == wid and arm_of(s["variant"]) == arm
        ]
        cells.append(usd(cell_all_in(sub, settle_spot)) if sub else "—")
    return " | ".join(cells)


def flip_eta_gate_block(
    reconstructed: list[dict], settle_spot: float, data_dir: Path
) -> list[str]:
    """Prospective flip-ETA gate scoreboard (TT-156 comment 15851).

    The gate is recorded at capture, never enforced; this block splits the
    day's clusters by their recorded bucket and accumulates gated vs ungated
    all-in P&L across every tagged session. Per width family throughout — no
    lumped grand total, same rule as the tranche block.
    """
    lines = ["## Flip-ETA gate (prospective)", ""]
    tagged = [s for s in reconstructed if s.get("gate_bucket")]
    if not tagged:
        return lines + ["gate tracking not active for this session", ""]

    extra_arms = [
        arm for arm in ("hw", "ghw") if any(arm_of(s["variant"]) == arm for s in tagged)
    ]
    arm_head = "".join(f" {arm}·w10 | {arm}·w25 | {arm}·w50 |" for arm in extra_arms)
    lines += [
        f"| Cluster (ET) | Direction | Bucket | 5m flip ETA | w10 | w25 | w50 |{arm_head}",
        "|---|---|---|---|---|---|---|" + "---|---|---|" * len(extra_arms),
    ]
    clusters: dict[tuple, list[dict]] = {}
    for s in tagged:
        clusters.setdefault(gate_cluster_key(s), []).append(s)
    for key in sorted(clusters):
        rows = clusters[key]
        first = rows[0]
        t_et = datetime.fromisoformat(first["opened_at"]).astimezone(ET)
        eta = first.get("gate_flip_eta_5m")
        arm_cells = "".join(
            f" {gate_width_cells(rows, settle_spot, arm)} |" for arm in extra_arms
        )
        lines.append(
            f"| {t_et:%H:%M} | {first['direction']} | {first['gate_bucket']} "
            f"| {'—' if eta is None else f'{eta:.1f}'} "
            f"| {gate_width_cells(rows, settle_spot)} |{arm_cells}"
        )

    gated = [s for s in tagged if s["gate_bucket"] in GATED_BUCKETS]
    ungated = [s for s in tagged if s["gate_bucket"] not in GATED_BUCKETS]
    lines += [
        "",
        "| Today (all-in) | w10 | w25 | w50 |",
        "|---|---|---|---|",
        f"| gated (imminent+near) | {gate_width_cells(gated, settle_spot)} |",
        f"| ungated | {gate_width_cells(ungated, settle_spot)} |",
    ]
    if "hw" in extra_arms:
        lines += [
            f"| gated · half-width | {gate_width_cells(gated, settle_spot, 'hw')} |",
            f"| ungated · half-width | {gate_width_cells(ungated, settle_spot, 'hw')} |",
        ]
    if "ghw" in extra_arms:
        # the enforced arm only ever holds gated clusters — one row, no
        # ungated counterpart by construction
        lines += [
            f"| gate-enforced · half-width | {gate_width_cells(gated, settle_spot, 'ghw')} |",
        ]

    cum_gated: list[dict] = []
    cum_ungated: list[dict] = []
    sessions, skipped_total = 0, 0
    for day_dir in sorted(p for p in data_dir.parent.iterdir() if p.is_dir()):
        rows, skipped, day_settle = events_only_day(day_dir)
        day_tagged = [s for s in rows if s.get("gate_bucket")]
        if not day_tagged:
            continue
        sessions += 1
        skipped_total += skipped
        for s in day_tagged:
            s["_settle"] = day_settle or 0.0
            (cum_gated if s["gate_bucket"] in GATED_BUCKETS else cum_ungated).append(s)

    def cum_cells(rows: list[dict], arm: str = "atm") -> str:
        cells = []
        for wid in ("w10", "w25", "w50"):
            sub = [
                s
                for s in rows
                if width_of(s["variant"]) == wid and arm_of(s["variant"]) == arm
            ]
            total = sum(cell_all_in([s], s["_settle"]) for s in sub)
            cells.append(usd(total) if sub else "—")
        return " | ".join(cells)

    lines += [
        "",
        f"| Cumulative since inception ({sessions} tagged sessions) | w10 | w25 | w50 |",
        "|---|---|---|---|",
        f"| gated (imminent+near) | {cum_cells(cum_gated)} |",
        f"| ungated | {cum_cells(cum_ungated)} |",
    ]
    if any(arm_of(s["variant"]) == "hw" for s in cum_gated + cum_ungated):
        lines += [
            f"| gated · half-width | {cum_cells(cum_gated, 'hw')} |",
            f"| ungated · half-width | {cum_cells(cum_ungated, 'hw')} |",
        ]
    if any(arm_of(s["variant"]) == "ghw" for s in cum_gated):
        lines.append(f"| gate-enforced · half-width | {cum_cells(cum_gated, 'ghw')} |")
    if skipped_total:
        lines.append(
            f"\n{skipped_total} restart-orphaned structures excluded from the "
            "cumulative rows (events-only reconstruction; day tables remain "
            "authoritative)."
        )
    return lines + [""]


STRATEGY_FAMS = ("w25_5m_m0", "w50_5m_m0")  # base completion rule only
MARGIN_OVERLAY_FAMS = ("w25_5m_m1",)  # tracked +1pt completion-credit arm
KALMAN_FAMS = ("w25_5m_m0_kal", "w25_5m_m0_kal_ef5")  # tracked Kalman tangent
# First session the Kalman arms ran live — earlier scoreboard rows show "—"
# (arm did not exist), not $0 (arm ran and stood aside).
KALMAN_ARM_START = "2026-08-31"
WIDTH_LABEL = {"w25_5m_m0": "25-wide", "w50_5m_m0": "50-wide"}


def strategy_structures(rows: list[dict]) -> list[dict]:
    return [s for s in rows if s["variant"] in STRATEGY_FAMS]


def classify_first_entries(rows: list[dict]) -> dict[str, bool]:
    """opened_at -> is-first-entry for one day's strategy clusters.

    A cluster is on-strategy when no prior strategy cluster opened within
    FIRST_ENTRY_WINDOW_MIN minutes (re-entries lost at every width in the
    2026-08-27 calibration).
    """
    from research.tt156_zero_dte_butterfly.config import FIRST_ENTRY_WINDOW_MIN

    stamps = sorted({s["opened_at"] for s in rows})
    out: dict[str, bool] = {}
    for t in stamps:
        dt = datetime.fromisoformat(t)
        out[t] = all(
            (dt - datetime.fromisoformat(p)).total_seconds()
            > FIRST_ENTRY_WINDOW_MIN * 60
            for p in stamps
            if p < t
        )
    return out


def regime_slim_lines(snapshots: list[dict], data_dir: Path) -> list[str]:
    """One-line regime stamp (the full block's calibration underperformed
    live; the rolling per-decision stamps in events are the useful record)."""
    spot_path = []
    for s in snapshots:
        t = snapshot_et(s)
        m = t.hour * 60 + t.minute
        if m < regime.MORNING_END_MINUTE:
            spot_path.append((m, s["spot"]))
    feats = regime.morning_features(spot_path, regime.trailing_atr(data_dir))
    if feats is None:
        return []
    call = regime.trend_call(feats)
    label = "no call" if call is None else f"{call[0]} (P≈{call[1]:.0%})"
    drive = "n/a" if feats.drive_atr is None else f"{feats.drive_atr:.2f}x ATR20"
    return [
        f"Regime @11:00: {label} · drive {drive} · retrace {feats.retrace_frac:.2f}",
        "",
    ]


def macd_state_label(hist: float, slope: float, direction: str) -> str:
    """Post-hoc 5m MACD state at entry: agree / converge / diverge.

    Forward-evidence labeling only (user-approved 2026-08-27) — MACD is not
    a live control; this classifies each trade's entry conditions from clean
    candles so the agree-vs-rest split accrues without touching the rule.
    """
    if (hist > 0) == (direction == "BULLISH"):
        return "agree"
    converging = (slope > 0) == (direction == "BULLISH") and abs(slope) > 1e-9
    if converging and abs(hist) / abs(slope) <= 10:
        return "converge"
    return "diverge"


def macd_entry_labels(rows: list[dict]) -> dict[str, str]:
    """opened_at -> MACD state label, from clean InfluxDB 5m candles.

    Degrades to {} when Influx or history is unavailable — the report never
    fails over a label.
    """
    if not rows:
        return {}
    try:
        import polars as pl

        from tastytrade.config import RedisConfigManager
        from tastytrade.providers.market import MarketDataProvider
        from tastytrade.providers.subscriptions import RedisSubscription
        from tastytrade.utils.time_series import initialize_influx_client

        day = datetime.fromisoformat(rows[0]["opened_at"]).astimezone(ET).date()
        influx = initialize_influx_client()
        provider = MarketDataProvider(
            data_feed=RedisSubscription(RedisConfigManager()), influx=influx
        )
        df = provider.download(
            symbol="SPX{=5m}",
            start=day - timedelta(days=4),
            stop=day + timedelta(days=1),
        )
        influx.close()
        if df.is_empty() or "close" not in df.columns:
            return {}
        df = (
            df.filter(pl.col("close").is_not_null())
            .unique(subset=["time"], keep="last")
            .sort("time")
        )
        close = df["close"].to_numpy()
        ema12 = pl.Series(close).ewm_mean(alpha=2 / 13, adjust=False).to_numpy()
        ema26 = pl.Series(close).ewm_mean(alpha=2 / 27, adjust=False).to_numpy()
        value = ema12 - ema26
        signal = pl.Series(value).ewm_mean(alpha=2 / 10, adjust=False).to_numpy()
        hist = value - signal
        series: dict[float, tuple[float, float]] = {}
        times = df["time"].to_list()
        for i, t in enumerate(times):
            epoch = t.replace(tzinfo=timezone.utc).timestamp()
            series[epoch] = (
                float(hist[i]),
                float(hist[i] - hist[i - 1]) if i else 0.0,
            )
        labels: dict[str, str] = {}
        for s in rows:
            opened = datetime.fromisoformat(s["opened_at"]).timestamp()
            bar = (opened - 60) // 300 * 300  # the sealed entry bar
            hs = series.get(bar) or series.get(bar - 300)
            if hs:
                labels[s["opened_at"]] = macd_state_label(hs[0], hs[1], s["direction"])
        return labels
    except Exception:
        return {}


def strategy_block(
    reconstructed: list[dict],
    settle_spot: float,
    macd_labels: dict[str, str] | None = None,
) -> list[str]:
    """The strategy: hull-only 5m entries, 10:00-13:00, flip exits."""
    lines = ["## Strategy — hull 5m, 25/50-wide, entries 10:00-13:00", ""]
    rows = strategy_structures(reconstructed)
    if not rows:
        return lines + ["No hull entries today — stood aside.", ""]
    labels = macd_labels if macd_labels is not None else macd_entry_labels(rows)
    lines += [
        "| Entry (ET) | Order | Width | Credit | All-in | Outcome | 5m MACD |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in sorted(rows, key=lambda s: (s["opened_at"], s["width"])):
        t_et = datetime.fromisoformat(s["opened_at"]).astimezone(ET)
        K, w = s["short_strike"], s["width"]
        order = (
            f"SOLD {K:g}/{K + w:g} call spread"
            if s["direction"] == "BEARISH"
            else f"SOLD {K:g}/{K - w:g} put spread"
        )
        outcome = order_outcome(s)
        label = labels.get(s["opened_at"], "—")
        lines.append(
            f"| {t_et:%H:%M} | {order} | {w:g} "
            f"| {s['entry_credit']:.2f} | {usd(cell_all_in([s], settle_spot))} "
            f"| {outcome} | {label} |"
        )
    return lines + [""]


def order_outcome(s: dict) -> str:
    if s.get("completion_credit"):
        return "fly locked"
    reason = s.get("close_reason")
    if reason == "forced_eod":
        return "closed 15:45 (EOD)"
    if reason in ("signal_hull", "signal_macd", "signal_kalman"):
        return "closed on signal"
    return reason or s["outcome"]


def structure_margin(s: dict, at: str) -> float:
    """1-lot margin (points) for a structure at timestamp ``at``.

    Open vertical: width − entry credit. Completed fly: width − total
    credit floored at zero — lossless flies free their margin, deficit
    (early-fly) conversions keep the shortfall at risk until settlement.
    """
    completed_at = s.get("completed_at")
    if completed_at and completed_at <= at and s.get("completion_credit") is not None:
        return max(0.0, s["width"] - (s["entry_credit"] + s["completion_credit"]))
    return s["width"] - s["entry_credit"]


def risk_block(reconstructed: list[dict]) -> list[str]:
    """Peak concurrent margin requirement and open-structure count per arm."""
    arms: dict[str, list[dict]] = {}
    for s in reconstructed:
        arms.setdefault(s["variant"], []).append(s)
    if not arms:
        return []
    lines = [
        "## Risk (peak intraday, per arm)",
        "",
        "| Arm | Max margin | Max open structures |",
        "|---|---|---|",
    ]
    for arm in sorted(arms):
        rows = arms[arm]
        points: set[str] = set()
        for s in rows:
            points.add(s["opened_at"])
            if s.get("completed_at"):
                points.add(s["completed_at"])
            if s.get("closed_at"):
                points.add(s["closed_at"])
        max_margin = 0.0
        max_open = 0
        for t in sorted(points):
            margin = 0.0
            n_open = 0
            for s in rows:
                if s["opened_at"] > t:
                    continue
                closed_at = s.get("closed_at")
                if closed_at and closed_at <= t:
                    continue
                n_open += 1
                margin += structure_margin(s, t)
            max_margin = max(max_margin, margin)
            max_open = max(max_open, n_open)
        lines.append(f"| {arm} | {usd(max_margin)} | {max_open} |")
    return lines + [""]


def off_strategy_lines(reconstructed: list[dict], settle_spot: float) -> list[str]:
    """Tracked-but-not-traded activity, compressed to a few lines."""
    lines = ["## Off-strategy grid (tracked)", ""]
    m_atm = [
        s
        for s in reconstructed
        if arm_of(s["variant"]) == "atm" and signal_of(s["variant"]) == "1m"
    ]
    hw = [s for s in reconstructed if arm_of(s["variant"]) == "hw"]
    ghw = [s for s in reconstructed if arm_of(s["variant"]) == "ghw"]
    tagged = [s for s in reconstructed if s.get("gate_bucket")]
    counts = {
        b: len({s["opened_at"] for s in tagged if s["gate_bucket"] == b})
        for b in ("imminent", "near", "firm", "confirms")
    }
    if tagged:
        lines.append(
            f"- Clusters by 5m-gate bucket (imm/near/firm/conf): "
            f"{counts['imminent']}/{counts['near']}/{counts['firm']}/{counts['confirms']}"
        )
    if m_atm:
        lines.append(f"- 1m ATM grid: {usd(cell_all_in(m_atm, settle_spot))}")
    if hw:
        lines.append(f"- Half-width arm: {usd(cell_all_in(hw, settle_spot))}")
    overlay = [s for s in reconstructed if s["variant"] in MARGIN_OVERLAY_FAMS]
    if overlay:
        lines.append(
            f"- Completion-margin overlay (+1 pt, tracked): "
            f"{usd(cell_all_in(overlay, settle_spot))}"
        )
    kal = [s for s in reconstructed if s["variant"] == "w25_5m_m0_kal"]
    kal_ef = [s for s in reconstructed if s["variant"] == "w25_5m_m0_kal_ef5"]
    if kal:
        lines.append(
            f"- Kalman tangent arm (q/r 0.025, tracked): "
            f"{usd(cell_all_in(kal, settle_spot))}"
        )
    if kal_ef:
        lines.append(
            f"- Kalman early-fly arm (tracked): {usd(cell_all_in(kal_ef, settle_spot))}"
        )
    if ghw:
        lines.append(f"- Gate-enforced arm: {usd(cell_all_in(ghw, settle_spot))}")
    if len(lines) == 2:  # header + blank only — nothing tracked off-strategy
        return []
    return lines + [""]


def settled_in_tent(s: dict, settle_spot: float | None) -> bool:
    """True when a locked fly settled strictly between its wings — the tent."""
    return (
        s["outcome"] == "settled"
        and s.get("completion_credit") is not None
        and settle_spot is not None
        and abs(settle_spot - s["short_strike"]) < s["width"]
    )


def tent_cell(rows: list[dict], settle_spot: float | None) -> str:
    """Counts of in-tent settlements by width, e.g. "1x25w 2x50w"."""
    parts = []
    for wid, label in (("w25", "25w"), ("w50", "50w")):
        n = sum(
            1
            for s in rows
            if width_of(s["variant"]) == wid and settled_in_tent(s, settle_spot)
        )
        if n:
            parts.append(f"{n}x{label}")
    return " ".join(parts) or "—"


def build_scoreboard(root: Path) -> str:
    """Standing running ledger (SCOREBOARD.md): every session under the live
    rule — hull-only 5m entries 10:00-13:00, flip exits, per-arm daily
    all-in totals. Rebuilt whole on each nightly report run."""
    header = [
        "# TT-156 Running Scoreboard",
        "",
        "All sessions under the live rule (hull-only 5m entries, "
        "10:00-13:00 ET, flip exits, complete into flies). Daily all-in "
        "dollars per arm. Rebuilt nightly.",
        "",
        "| Date | 25-wide | 25-wide +1pt | 25-wide early-fly | 50-wide "
        "| 25-wide kal | kal early-fly | In tent | Run 25-wide | Run 50-wide |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    body: list[str] = []
    run25 = run50 = 0.0
    quiet = 0
    for day_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            date.fromisoformat(day_dir.name)
        except ValueError:
            continue  # archives and tooling dirs (clean_resim, live_pre_fix, …)
        rows, _, day_settle = events_only_day(day_dir)
        by_var: dict[str, float] = {}
        for s in rows:
            by_var[s["variant"]] = by_var.get(s["variant"], 0.0) + cell_all_in(
                [s], day_settle or 0.0
            )
        if not by_var:
            quiet += 1
            continue
        d25 = by_var.get("w25_5m_m0", 0.0)
        d25m1 = by_var.get("w25_5m_m1", 0.0)
        d25ef = by_var.get("w25_5m_m0_ef5", 0.0)
        d50 = by_var.get("w50_5m_m0", 0.0)
        run25 += d25
        run50 += d50
        if day_dir.name >= KALMAN_ARM_START:
            dkal = usd(by_var.get("w25_5m_m0_kal", 0.0))
            dkal_ef = usd(by_var.get("w25_5m_m0_kal_ef5", 0.0))
        else:
            dkal = dkal_ef = "—"
        strat = [s for s in rows if s["variant"] in STRATEGY_FAMS]
        body.append(
            f"| {day_dir.name} | {usd(d25)} | {usd(d25m1)} | {usd(d25ef)} "
            f"| {usd(d50)} | {dkal} | {dkal_ef} "
            f"| {tent_cell(strat, day_settle)} | {usd(run25)} | {usd(run50)} |"
        )
    footer = [
        "",
        f"Sessions with no entry: {quiet}.",
        "",
        "In tent = locked fly whose settlement landed between the wings "
        "(counts by width, primary arms).",
        "",
        "kal columns: Kalman tangent tracked arms (velocity sign flips, "
        f"q/r 0.025), live from {KALMAN_ARM_START}; — before that (arm did "
        "not exist).",
        "",
    ]
    return "\n".join(header + body + footer)


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
    lines += regime_slim_lines(snapshots, data_dir)
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
    if not reconstructed:
        lines += [
            "## No trades — out-of-scope regime",
            "",
            "The setup made zero entries today. Confluence is a transition "
            "detector (Hull + MACD must cross together on a sealed candle), so a "
            "gap-and-chop or instant-directional day produces no fresh dual-cross "
            "and the strategy correctly stands aside. A no-trade session is a "
            "valid regime observation of this setup's selectivity, not a missed "
            "trade — there is no P&L table to report.",
            "",
        ]
        return "\n".join(lines)
    lines += strategy_block(reconstructed, settle_spot)
    lines += risk_block(reconstructed)
    lines += off_strategy_lines(reconstructed, settle_spot)

    # research artifact preserved on disk, out of the daily text
    sweep = retro_sweep(snapshots)
    if sweep:
        (data_dir / "retro_sweep.json").write_text(
            json.dumps(sweep, indent=2, default=str)
        )

    lines += [
        "## Caveats",
        "",
        "- Mid fills; all-in = mid − per-spread concession+fees − settlement "
        "fees. Completion thresholds at mid overstate live completion rates.",
        "- First-entry/stop calibrations are in-sample (2026-08-27); this "
        "report is the forward test.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="TT-156 EOD report")
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    report = build_report(args.data_dir)
    out = args.data_dir / "REPORT.md"
    out.write_text(report)
    board = args.data_dir.parent / "SCOREBOARD.md"
    board.write_text(build_scoreboard(args.data_dir.parent))
    print(f"Report written to {out}; scoreboard refreshed at {board}")


if __name__ == "__main__":
    main()
