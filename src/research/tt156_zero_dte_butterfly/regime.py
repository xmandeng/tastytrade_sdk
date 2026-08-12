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

from dataclasses import dataclass

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
