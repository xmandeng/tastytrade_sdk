"""Regime read @ 11:00 — prospective trend-day odds from morning price action.

Calibrated 2026-08-12 on 377 SPX sessions (Feb 2025 - Aug 2026, 1m candles):
trend day := |close - open| / day range >= 0.7 (base rate 28.9%). The two
features that discriminate by 11:00 ET are the opening drive (|net move
9:30-11:00| / trailing 20-day RTH range) and the deepest morning retracement
as a fraction of that net move. Measured conditional odds:

  drive >= Q75 and retrace <= Q25 -> P(trend) = 0.49
  either one strong               -> P(trend) ~ 0.47
  drive <= Q25 or retrace >= Q75  -> P(trend) = 0.11
  otherwise                       -> base 0.29

The asymmetry is the point: mornings rule trend days OUT far more reliably
than they call them. Thresholds are frozen calibration, not tunables.
"""

import gzip
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from research.tt156_zero_dte_butterfly.config import ET

# Frozen calibration (377 sessions; see module docstring).
DRIVE_Q25 = 0.170
DRIVE_Q75 = 0.625
RETRACE_Q25 = 0.577
RETRACE_Q75 = 2.306
P_TREND_BASE = 0.29
P_TREND_ELEVATED = 0.49
P_TREND_LEANING = 0.47
P_TREND_UNLIKELY = 0.11

MORNING_END_MINUTE = 11 * 60  # features freeze at 11:00 ET
RTH_START_MINUTE = 9 * 60 + 30


@dataclass(frozen=True)
class MorningFeatures:
    net_pts: float  # signed 9:30 -> 11:00 move
    drive_atr: float | None  # |net| / trailing 20-day RTH range (None: no ATR)
    retrace_frac: float  # deepest counter-move / |net|, capped at 3


def morning_features(
    spot_path: list[tuple[int, float]], atr: float | None
) -> MorningFeatures | None:
    """Features from the 9:30-11:00 spot path: [(minute_of_day_et, spot)].

    Returns None when the morning window is too sparse to trust (fewer than
    30 observations) — the read degrades to "insufficient data", never to a
    guess.
    """
    am = sorted(
        (m, s) for m, s in spot_path if RTH_START_MINUTE <= m < MORNING_END_MINUTE
    )
    if len(am) < 30:
        return None
    spots = [s for _, s in am]
    net = spots[-1] - spots[0]
    scale = max(abs(net), 1e-9)
    deepest = 0.0
    extreme = spots[0]
    for s in spots:
        if net >= 0:
            extreme = max(extreme, s)
            deepest = max(deepest, extreme - s)
        else:
            extreme = min(extreme, s)
            deepest = max(deepest, s - extreme)
    return MorningFeatures(
        net_pts=net,
        drive_atr=None if atr is None or atr <= 0 else abs(net) / atr,
        retrace_frac=min(deepest / scale, 3.0),
    )


def rolling_state(
    spot_path: list[tuple[int, float]], atr: float | None
) -> dict[str, float | None] | None:
    """Drive/retrace measured from 9:30 up to *now* — a reading that is
    current at the moment of a decision (entry, completion, lock-vs-ticket),
    unlike the one-shot 11:00 forecast. Same arithmetic, no morning cutoff.

    Returns None while the session is too young to read (<30 observations).
    """
    rth = sorted((m, s) for m, s in spot_path if m >= RTH_START_MINUTE)
    if len(rth) < 30:
        return None
    spots = [s for _, s in rth]
    net = spots[-1] - spots[0]
    scale = max(abs(net), 1e-9)
    deepest = 0.0
    extreme = spots[0]
    for s in spots:
        if net >= 0:
            extreme = max(extreme, s)
            deepest = max(deepest, extreme - s)
        else:
            extreme = min(extreme, s)
            deepest = max(deepest, s - extreme)
    return {
        "drive_atr": None if atr is None or atr <= 0 else abs(net) / atr,
        "retrace_frac": min(deepest / scale, 3.0),
    }


def day_rth_range(day_dir: Path) -> float | None:
    """RTH spot range of a prior session from its snapshot file.

    Extracts ts/spot per line without parsing the options arrays (the file's
    own json.dumps key order makes the split stable); a malformed line is
    skipped, and a truncated archive yields the range accumulated so far.
    """
    path = day_dir / "chain_snapshots.jsonl.gz"
    if not path.exists():
        return None
    lo, hi = None, None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    ts = line.split('"ts": "', 1)[1].split('"', 1)[0]
                    spot = float(line.split('"spot": ', 1)[1].split(",", 1)[0])
                except (IndexError, ValueError):
                    continue
                t = datetime.fromisoformat(ts).astimezone(ET)
                m = t.hour * 60 + t.minute
                if not (RTH_START_MINUTE <= m < 16 * 60):
                    continue
                if lo is None or spot < lo:
                    lo = spot
                if hi is None or spot > hi:
                    hi = spot
    except (EOFError, OSError, zlib.error):
        pass
    if lo is None or hi is None or hi <= lo:
        return None
    return hi - lo


def trailing_atr(data_dir: Path, lookback: int = 20, minimum: int = 5) -> float | None:
    """Mean RTH range of up to `lookback` prior sessions; None below `minimum`."""
    prior = sorted(
        (p for p in data_dir.parent.iterdir() if p.is_dir() and p.name < data_dir.name),
        reverse=True,
    )
    ranges = []
    for day_dir in prior:
        r = day_rth_range(day_dir)
        if r is not None:
            ranges.append(r)
        if len(ranges) >= lookback:
            break
    if len(ranges) < minimum:
        return None
    return sum(ranges) / len(ranges)


def trend_call(f: MorningFeatures) -> tuple[str, float] | None:
    """(label, P(trend)) from frozen calibration; None without an ATR."""
    if f.drive_atr is None:
        return None
    strong_drive = f.drive_atr >= DRIVE_Q75
    shallow = f.retrace_frac <= RETRACE_Q25
    if strong_drive and shallow:
        return "trend-elevated", P_TREND_ELEVATED
    if f.drive_atr <= DRIVE_Q25 or f.retrace_frac >= RETRACE_Q75:
        return "trend-unlikely", P_TREND_UNLIKELY
    if strong_drive or shallow:
        return "trend-leaning", P_TREND_LEANING
    return "trend-neutral", P_TREND_BASE
