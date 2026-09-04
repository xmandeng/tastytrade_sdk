"""Settlement price: the official SPX close, and nothing else.

SPXW PM-settled options settle to the official SPX closing value. The
index keeps updating for several minutes after 16:00 ET as late prints
arrive, so a snapshot spot taken at or before 16:00 is never that value;
the audit of 56 sessions found a median miss of 1.5 points and one of
15.6. The official close is the close of the SPX daily candle in InfluxDB
for the session date, final by about 16:05 ET.

There is no fallback. If the candle for the session date is missing, or
the session has not closed yet, the caller gets ``None`` and must leave
its structures unsettled; ``restate`` completes the day later.

Usage: uv run python -m research.tt156_zero_dte_butterfly.settlement restate research_data/TT-156 [--dry-run]
"""

import argparse
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Protocol

from research.tt156_zero_dte_butterfly.config import ET

logger = logging.getLogger(__name__)

SYMBOL = "SPX"
# The index's final close has been published by 16:05 on every session
# audited; before that the daily candle still carries a running value.
CLOSE_FINAL = time(16, 5)
PINFLY_PREFIX = "pinfly"


class DailyCandleSource(Protocol):
    def get_daily_candle(self, symbol: str, target_date: date) -> object: ...


def official_close(
    source: DailyCandleSource, day: date, now: datetime | None = None
) -> float | None:
    """Official SPX close for ``day`` or ``None`` when it is not final yet.

    ``get_daily_candle`` walks back to earlier trading days when the target
    date has no candle; that is exactly the substitution a settlement must
    never make, so the candle's own date is checked against ``day``.
    """
    now = now or datetime.now(ET)
    if day == now.astimezone(ET).date() and now.astimezone(ET).time() < CLOSE_FINAL:
        logger.error(
            "Official close for %s is not final before %s ET", day, CLOSE_FINAL
        )
        return None
    try:
        candle = source.get_daily_candle(SYMBOL, day)
    except ValueError:
        logger.error("No SPX daily candle for %s", day)
        return None
    candle_time = getattr(candle, "time", None)
    close = getattr(candle, "close", None)
    if candle_time is None or candle_time.date() != day or close is None:
        logger.error(
            "SPX daily candle for %s came back dated %s; refusing to settle",
            day,
            candle_time,
        )
        return None
    return float(close)


def settled_pnl_points(row: dict, close: float) -> float:
    """Recompute a SETTLEMENT row's P&L at ``close``.

    Mirrors ``ButterflySimulator.settle`` (iron fly: total credit less the
    capped distance from the short strike) and ``PinFlySimulator.settle``
    (long fly: tent payoff plus the negative entry credit, i.e. the debit).
    """
    distance = abs(close - float(row["short_strike"]))
    width = float(row["width"])
    entry_credit = float(row["entry_credit"])
    if str(row.get("variant", "")).startswith(PINFLY_PREFIX):
        return max(0.0, width - distance) + entry_credit
    total = entry_credit + float(row.get("completion_credit") or 0.0)
    return total - min(distance, width)


@dataclass
class DayRestatement:
    day_dir: Path
    close: float
    before: dict[str, float] = field(default_factory=dict)  # variant -> pnl pts
    after: dict[str, float] = field(default_factory=dict)
    rows_changed: int = 0
    previous_spot: float | None = None


def restate_day(day_dir: Path, close: float, dry_run: bool = False) -> DayRestatement:
    """Re-settle every SETTLED row in ``day_dir`` at ``close``.

    Rewrites ``pnl_points`` and ``settlement_spot`` on SETTLEMENT rows in
    events.jsonl (pin-fly rows gain the field) and ``settlement_spot`` in
    final_results.json. Nothing else in the ledger is touched.
    """
    result = DayRestatement(day_dir=day_dir, close=close)
    events_path = day_dir / "events.jsonl"
    if not events_path.exists():
        return result
    rows = [
        json.loads(line)
        for line in events_path.read_text().splitlines()
        if line.strip()
    ]
    out_lines: list[str] = []
    for row in rows:
        if row.get("event") == "SETTLEMENT" and row.get("status") == "SETTLED":
            variant = str(row["variant"])
            old = float(row.get("pnl_points") or 0.0)
            new = settled_pnl_points(row, close)
            if result.previous_spot is None and row.get("settlement_spot") is not None:
                result.previous_spot = float(row["settlement_spot"])
            result.before[variant] = result.before.get(variant, 0.0) + old
            result.after[variant] = result.after.get(variant, 0.0) + new
            if abs(new - old) > 1e-9 or row.get("settlement_spot") != close:
                result.rows_changed += 1
            row["pnl_points"] = new
            row["settlement_spot"] = close
        out_lines.append(json.dumps(row, default=str))
    if dry_run:
        return result
    events_path.write_text("\n".join(out_lines) + "\n")
    results_path = day_dir / "final_results.json"
    if results_path.exists():
        results = json.loads(results_path.read_text())
        if result.previous_spot is None and results.get("settlement_spot") is not None:
            result.previous_spot = float(results["settlement_spot"])
        results["settlement_spot"] = close
        results_path.write_text(json.dumps(results, indent=2, default=str))
    return result


def session_dirs(root: Path) -> list[Path]:
    """Every per-day ledger directory under ``root``, including the
    pre-fix archive; test runs (``YYYY-MM-DD-test``) are not ledger."""
    found: list[Path] = []
    for candidate in sorted(root.glob("*")) + sorted((root / "live_pre_fix").glob("*")):
        if not candidate.is_dir():
            continue
        try:
            date.fromisoformat(candidate.name)
        except ValueError:
            continue
        found.append(candidate)
    return found


def backup_ledger(root: Path) -> Path:
    stamp = datetime.now(ET).strftime("%Y%m%d-%H%M%S")
    target = root.parent / f"{root.name}.pre-restate-{stamp}"
    shutil.copytree(root, target, ignore=shutil.ignore_patterns("*.gz", "*.png"))
    return target


def restate(
    root: Path, source: DailyCandleSource, dry_run: bool
) -> list[DayRestatement]:
    dirs = session_dirs(root)
    if not dry_run:
        logger.info("Ledger backed up to %s", backup_ledger(root))
    done: list[DayRestatement] = []
    for day_dir in dirs:
        day = date.fromisoformat(day_dir.name)
        close = official_close(source, day)
        if close is None:
            print(f"{day_dir}: no official close, left untouched")
            continue
        done.append(restate_day(day_dir, close, dry_run=dry_run))
    return done


def print_summary(done: list[DayRestatement]) -> None:
    by_variant: dict[str, list[float]] = {}
    for d in done:
        for v in set(d.before) | set(d.after):
            acc = by_variant.setdefault(v, [0.0, 0.0])
            acc[0] += d.before.get(v, 0.0)
            acc[1] += d.after.get(v, 0.0)
    print(
        f"sessions restated: {len(done)}; rows rewritten: {sum(d.rows_changed for d in done)}"
    )
    print(f"{'variant':>26} {'before pts':>11} {'after pts':>10} {'diff $':>9}")
    for v, (b, a) in sorted(by_variant.items()):
        print(f"{v:>26} {b:>11.2f} {a:>10.2f} {(a - b) * 100:>+9,.0f}")


def influx_source() -> tuple[DailyCandleSource, object]:
    from tastytrade.config import RedisConfigManager
    from tastytrade.providers.market import MarketDataProvider
    from tastytrade.providers.subscriptions import RedisSubscription
    from tastytrade.utils.time_series import initialize_influx_client

    influx = initialize_influx_client()
    provider = MarketDataProvider(
        data_feed=RedisSubscription(RedisConfigManager()), influx=influx
    )
    return provider, influx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TT-156 settlement at the official SPX close"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    rs = sub.add_parser(
        "restate", help="re-settle every recorded session at the official close"
    )
    rs.add_argument("root", type=Path, help="ledger root, e.g. research_data/TT-156")
    rs.add_argument(
        "--dry-run", action="store_true", help="compute and print, write nothing"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    source, influx = influx_source()
    try:
        done = restate(args.root, source, dry_run=args.dry_run)
    finally:
        influx.close()  # type: ignore[attr-defined]
    print_summary(done)


if __name__ == "__main__":
    main()
