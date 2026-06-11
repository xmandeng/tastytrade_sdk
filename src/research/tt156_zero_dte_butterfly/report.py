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
    return f"{value:+.2f} pts (${value * CONTRACT_MULTIPLIER:+,.0f})"


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
            # Orphaned by a collector restart — replay the live rules from
            # snapshots: complete at threshold, exit on opposing engine flip
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
        "## Day overview",
        "",
        f"- Snapshots captured: {len(snapshots)} (cadence {header['cadence_seconds']}s)",
        f"- SPX path: open≈{spots[0]:.2f}, high {max(spots):.2f}, "
        f"low {min(spots):.2f}, last {spots[-1]:.2f}",
        f"- Settlement spot used: {results.get('settlement_spot')}",
        f"- Prior close: {header['index_summary'].get('prev_close')}",
        "",
        "## Live paper-trading results (mid-price fills)",
        "",
        "Reconstructed from events.jsonl — spans all collector instances; "
        "structures orphaned by a restart are settled/closed from the "
        "snapshot record under the live rules.",
        "",
    ]
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
    lines += variant_table(reconstructed, variant_names)
    orphans = [s for s in reconstructed if s.get("orphaned")]
    total_pnl = sum(s["pnl_points"] or 0.0 for s in reconstructed)
    lines += [
        "",
        f"Structures reconstructed: {len(reconstructed)} "
        f"({len(orphans)} orphaned by restarts, resolved from snapshots)",
        f"Skipped entries (unusable quotes, last instance): {results.get('skipped_entries', 0)}",
        *risk_and_whipsaw_lines(data_dir, reconstructed),
        f"**Total live paper P&L: {fmt_pts(total_pnl)}** per 1-lot per variant",
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
        "- Single session; mid-price fills assumed on every leg; no fees/slippage.",
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
