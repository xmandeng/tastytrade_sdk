"""Pin-fly tracked arms (user-approved 2026-08-31, condor-overlay study):
a defined-debit long ATM butterfly bought into the afternoon pin.

At the first snapshot in the 14:00 ET entry window, buy the 25-wide ATM
call fly (+1 body−width / −2 body / +1 body+width) at mid and hold to
settlement. Max loss is the debit — no tail is sold (the short-premium
family was falsified; see docs/TT156_CONDOR_OVERLAY_STUDY.md).

Arms differ only in their entry trigger:
- pinfly25_all         every trading day (control)
- pinfly25_notent      only if no kalman-family tent exists yet (cushion
                       mandate: deploy only when the day hasn't paid)
- pinfly25_notent_mid  no-tent AND spot inside the middle half of the
                       day's range (the 20-month history shows the
                       afternoon pin concentrates mid-range)

Events reuse the ledger Structure schema: direction NEUTRAL, short_strike
is the fly body, entry_credit is NEGATIVE (a debit), pnl_points at
settlement = payoff + entry_credit (mid convention; costs applied at
report time like every other arm).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Callable

from research.tt156_zero_dte_butterfly.config import ET
from research.tt156_zero_dte_butterfly.simulator import (
    LegFill,
    Quotes,
    Structure,
    leg_mid,
)

logger = logging.getLogger(__name__)

PINFLY_WIDTH = 25.0
# Entry window: first snapshot at/after 14:00 ET. The hard end guards a
# restarted collector from buying a stale fly late in the afternoon.
PINFLY_ENTRY_START = time(14, 0)
PINFLY_ENTRY_END = time(14, 10)


@dataclass(frozen=True)
class PinFlyArm:
    name: str
    trigger: str  # "all" | "notent" | "notent_mid"


def default_pinfly_arms() -> list[PinFlyArm]:
    return [
        PinFlyArm("pinfly25_all", "all"),
        PinFlyArm("pinfly25_notent", "notent"),
        PinFlyArm("pinfly25_notent_mid", "notent_mid"),
    ]


def fly_debit(
    quotes: Quotes, spot: float, width: float
) -> tuple[float, float, list[LegFill]] | None:
    """Mid debit for the long ATM call fly. Returns (debit, body, legs)."""
    strikes = sorted({k for k, _ in quotes})
    if not strikes:
        return None
    body = min(strikes, key=lambda k: abs(k - spot))
    lo, hi = body - width, body + width
    mids = {}
    legs: list[LegFill] = []
    for strike, action in ((lo, "BTO"), (body, "STO"), (hi, "BTO")):
        quote = quotes.get((strike, "C"))
        mid = leg_mid(quote)
        if mid is None or quote is None:
            return None
        mids[strike] = mid
        legs.append(
            LegFill(
                occ_strike=strike,
                option_type="C",
                action=action,
                bid=quote.get("bid"),
                ask=quote.get("ask"),
                mid=mid,
            )
        )
    # the body is sold twice
    legs.insert(2, legs[1])
    debit = mids[lo] - 2 * mids[body] + mids[hi]
    if debit <= 0:
        return None
    return debit, body, legs


class PinFlySimulator:
    """Runs the pin-fly arms against the same snapshot stream as the main
    simulator. One decision per day at the entry window; hold to settle."""

    def __init__(
        self,
        arms: list[PinFlyArm],
        tent_exists: Callable[[], bool],
        event_sink: Callable[[dict], None] | None = None,
    ) -> None:
        self.arms = arms
        self.tent_exists = tent_exists
        self.event_sink = event_sink
        self.structures: list[Structure] = []
        self.entry_done = False
        self.day_high: float | None = None
        self.day_low: float | None = None

    def emit(self, kind: str, ts: datetime, structure: Structure) -> None:
        from dataclasses import asdict

        record = {"event": kind, "ts": ts.isoformat(), **asdict(structure)}
        logger.info(
            "%s %s body=%s debit=%.2f pnl=%s",
            kind,
            structure.variant,
            structure.short_strike,
            -structure.entry_credit,
            structure.pnl_points,
        )
        if self.event_sink:
            self.event_sink(record)

    def triggered(self, arm: PinFlyArm, spot: float) -> bool:
        if arm.trigger == "all":
            return True
        if self.tent_exists():
            return False
        if arm.trigger == "notent":
            return True
        # notent_mid: spot inside the middle half of the day's range so far
        if self.day_high is None or self.day_low is None:
            return False
        span = self.day_high - self.day_low
        if span <= 0:
            return True  # flat day is the ultimate mid-range
        pos = (spot - self.day_low) / span
        return 0.25 <= pos <= 0.75

    def on_snapshot(self, ts: datetime, spot: float, quotes: Quotes) -> None:
        ts_et = ts.astimezone(ET)
        if ts_et.time() < PINFLY_ENTRY_START:
            self.day_high = spot if self.day_high is None else max(self.day_high, spot)
            self.day_low = spot if self.day_low is None else min(self.day_low, spot)
            return
        if self.entry_done or ts_et.time() >= PINFLY_ENTRY_END:
            self.entry_done = True  # restart past the window: no stale entry
            return
        self.entry_done = True
        priced = fly_debit(quotes, spot, PINFLY_WIDTH)
        if priced is None:
            logger.warning("Pin fly: could not price the ATM fly — no entries")
            return
        debit, body, legs = priced
        for arm in self.arms:
            if not self.triggered(arm, spot):
                continue
            structure = Structure(
                variant=arm.name,
                direction="NEUTRAL",
                short_strike=body,
                width=PINFLY_WIDTH,
                opened_at=ts.isoformat(),
                entry_spot=spot,
                entry_credit=-debit,
                entry_legs=list(legs),
                signal_trigger=f"pinfly_{arm.trigger}",
            )
            self.structures.append(structure)
            self.emit("ENTRY", ts, structure)

    def settle(self, ts: datetime, settlement_spot: float) -> None:
        for s in self.structures:
            if s.status != "OPEN":
                continue
            payoff = max(0.0, s.width - abs(settlement_spot - s.short_strike))
            s.pnl_points = payoff + s.entry_credit
            s.status = "SETTLED"
            self.emit("SETTLEMENT", ts, s)
