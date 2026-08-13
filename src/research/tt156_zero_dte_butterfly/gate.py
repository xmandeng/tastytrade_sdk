"""Flip-ETA gate: numeric MACD context stamped on entries at capture time.

The gate is recorded, never enforced — the full grid keeps trading as the
control group. Bucket semantics (TT-156 comment 15851): the researched edge
is entries fired while the 5m MACD histogram still opposes the entry
direction but is converging toward its own zero-cross within
``GATE_ETA_NEAR`` sealed bars.
"""

from research.tt156_zero_dte_butterfly.config import GATE_ETA_IMMINENT, GATE_ETA_NEAR

GATED_BUCKETS = ("imminent", "near")


def flip_eta(hist: float | None, slope: float | None) -> float | None:
    """Sealed bars until the histogram crosses zero, if converging.

    ``hist`` is MACD Value − signal on the last sealed bar; ``slope`` is its
    change from the prior sealed bar. Converging means the histogram is
    shrinking toward zero (opposite signs). Diverging, flat, or unknown
    inputs have no ETA.
    """
    if hist is None or slope is None or slope == 0 or hist * slope >= 0:
        return None
    return abs(hist / slope)


def gate_bucket(
    hist_5m: float | None, slope_5m: float | None, direction: str
) -> str | None:
    """Classify an entry against the 5m MACD state.

    imminent / near — 5m opposes the entry direction, flip ETA within
    threshold (the researched edge); firm — opposes with no near flip;
    confirms — 5m already agrees with the direction.
    """
    if hist_5m is None:
        return None
    opposes = (hist_5m > 0) != (direction == "BULLISH")
    if not opposes:
        return "confirms"
    eta = flip_eta(hist_5m, slope_5m)
    if eta is not None and eta <= GATE_ETA_IMMINENT:
        return "imminent"
    if eta is not None and eta <= GATE_ETA_NEAR:
        return "near"
    return "firm"
