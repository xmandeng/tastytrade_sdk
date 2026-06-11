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
) -> dict:
    """Walk forward: complete at threshold, else forced close at 15:45."""
    for snap in snapshots[entry_idx + 1 :]:
        ts = snapshot_et(snap)
        quotes = snapshot_quotes(snap)
        if ts.time() <= LAST_COMPLETION:
            counter = counter_credit(quotes, direction, strike, width)
            if counter is not None and credit + counter >= width:
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


def build_report(data_dir: Path) -> str:
    header = json.loads((data_dir / "header.json").read_text())
    results = json.loads((data_dir / "final_results.json").read_text())
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
        "| Variant | Entries | Completed | Closed early | P&L |",
        "|---|---|---|---|---|",
    ]
    for name, row in results["variants"].items():
        lines.append(
            f"| {name} | {row['entries']} | {row['completed']} | "
            f"{row['closed_incomplete']} | {fmt_pts(row['pnl_points'])} |"
        )
    lines += [
        "",
        f"Skipped entries (unusable quotes): {results.get('skipped_entries', 0)}",
        f"**Total live paper P&L: {fmt_pts(results['total_pnl_points'])}** per 1-lot per variant",
        "",
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
