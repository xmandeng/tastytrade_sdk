"""Entry point for the TT-156 research day.

Usage (from repo root):
    uv run python -m research.tt156_zero_dte_butterfly.run_day
    uv run python -m research.tt156_zero_dte_butterfly.run_day --test

``--test`` runs 3 immediate cycles regardless of the clock into a
``test/`` subdirectory — a plumbing check, not a trading session.
"""

import argparse
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from research.tt156_zero_dte_butterfly.collector import DayCollector
from research.tt156_zero_dte_butterfly.config import ET, RunConfig

DATA_ROOT = Path("research_data/TT-156")


def build_config(test_mode: bool, cadence: float) -> RunConfig:
    today = datetime.now(tz=ET).date().isoformat()
    if test_mode:
        return RunConfig(
            data_dir=DATA_ROOT / f"{today}-test",
            cadence_seconds=cadence,
            max_cycles=3,
            ignore_session_times=True,
        )
    return RunConfig(data_dir=DATA_ROOT / today, cadence_seconds=cadence)


def main() -> None:
    parser = argparse.ArgumentParser(description="TT-156 0DTE butterfly research day")
    parser.add_argument("--test", action="store_true", help="3-cycle plumbing check")
    parser.add_argument("--cadence", type=float, default=15.0)
    args = parser.parse_args()

    config = build_config(args.test, args.cadence)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.data_dir / "collector.log"),
        ],
    )

    results = asyncio.run(DayCollector(config).run())
    print(f"Total paper P&L (points): {results['total_pnl_points']:+.2f}")


if __name__ == "__main__":
    main()
