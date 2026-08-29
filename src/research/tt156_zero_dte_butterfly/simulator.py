"""Paper simulator for vertical → counter-vertical (iron butterfly) legging.

Entry: on a confluence OPEN signal, sell the ATM vertical at mid —
BEARISH → bear call spread (short K call, long K+w call);
BULLISH → bull put spread (short K put, long K-w put).

Completion: when the counter vertical at the same short strike can be sold
so that total credit >= width + margin, open it. The resulting iron
butterfly has locked worst-case P&L = total credit - width >= margin.

Exit when incomplete: opposing CLOSE signal from the engine, or forced
close at 15:45 ET. Completed butterflies are held to 16:00 settlement.

All fills are at mid-price. P&L is in SPX points (×100 = dollars/contract).
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from tastytrade.analytics.engines.models import TradeSignal

from research.tt156_zero_dte_butterfly.gate import GATED_BUCKETS, gate_bucket

from research.tt156_zero_dte_butterfly.config import (
    ET,
    FORCED_CLOSE,
    HALFWIDTH_MAX_STEPS,
    LAST_COMPLETION,
    STRIKE_STEP,
    VariantConfig,
)

logger = logging.getLogger(__name__)

# quotes mapping: (strike, "C"|"P") -> market-data field dict
Quotes = dict[tuple[float, str], dict[str, float | None]]


@dataclass
class LegFill:
    occ_strike: float
    option_type: str  # "C" / "P"
    action: str  # "STO" / "BTO" / "BTC" / "STC"
    bid: float | None
    ask: float | None
    mid: float | None


@dataclass
class Structure:
    variant: str
    direction: str  # BULLISH / BEARISH (entry signal direction)
    short_strike: float
    width: float
    opened_at: str
    entry_spot: float
    entry_credit: float
    entry_legs: list[LegFill]
    signal_trigger: str
    status: str = "OPEN"  # OPEN -> COMPLETED | CLOSED -> SETTLED
    # Flip-ETA gate context captured at entry (see gate.py); recorded once,
    # never mutated. None on structures from before gate tracking existed.
    gate_bucket: str | None = None
    gate_hist_5m: float | None = None
    gate_slope_5m: float | None = None
    gate_flip_eta_5m: float | None = None
    gate_hist_1m: float | None = None
    gate_slope_1m: float | None = None
    gate_flip_eta_1m: float | None = None
    # Rolling regime state at the two decision moments (see regime.rolling_state):
    # drive/retrace measured from 9:30 up to that instant, not the 11:00 forecast.
    regime_drive_entry: float | None = None
    regime_retrace_entry: float | None = None
    regime_drive_completion: float | None = None
    regime_retrace_completion: float | None = None
    completed_at: str | None = None
    completion_spot: float | None = None
    completion_credit: float | None = None
    completion_legs: list[LegFill] = field(default_factory=list)
    closed_at: str | None = None
    close_cost: float | None = None
    close_reason: str | None = None
    pnl_points: float | None = None


def leg_mid(quote: dict[str, float | None] | None) -> float | None:
    """Mid from bid/ask; a missing/zero ask means the quote is unusable."""
    if quote is None:
        return None
    bid, ask = quote.get("bid"), quote.get("ask")
    if ask is None or ask <= 0:
        return None
    return ((bid or 0.0) + ask) / 2


def vertical_credit(
    quotes: Quotes, short_strike: float, long_strike: float, option_type: str
) -> tuple[float, list[LegFill]] | None:
    """Mid credit for selling the short leg and buying the long leg."""
    short_quote = quotes.get((short_strike, option_type))
    long_quote = quotes.get((long_strike, option_type))
    short_mid = leg_mid(short_quote)
    long_mid = leg_mid(long_quote)
    if (
        short_mid is None
        or long_mid is None
        or short_quote is None
        or long_quote is None
    ):
        return None
    credit = short_mid - long_mid
    legs = [
        LegFill(
            short_strike,
            option_type,
            "STO",
            short_quote.get("bid"),
            short_quote.get("ask"),
            short_mid,
        ),
        LegFill(
            long_strike,
            option_type,
            "BTO",
            long_quote.get("bid"),
            long_quote.get("ask"),
            long_mid,
        ),
    ]
    return credit, legs


def atm_strike(spot: float) -> float:
    return round(spot / STRIKE_STEP) * STRIKE_STEP


def signal_matches(variant: VariantConfig, signal: TradeSignal) -> bool:
    """Route a signal to a variant: same symbol AND same signal family.

    Kalman arms enter only on the kalman tangent but exit on EITHER
    family's flip — the hull flip is an independent kill-switch backstop
    (user directive 2026-08-28; bound 12 times in the 53-session resim,
    slightly additive on every arm). Hull arms stay a pure control: their
    own family only. Signals without an ``engine`` attribute (replay-rig
    stubs) belong to the hull family, so every pre-Kalman tool keeps
    routing exactly as before.
    """
    if signal.eventSymbol != variant.signal_symbol:
        return False
    from_kalman = getattr(signal, "engine", None) == "kalman"
    if variant.signal_source == "kalman":
        return signal.signal_type == "CLOSE" or from_kalman
    return not from_kalman


def halfwidth_entry(
    direction: str, spot: float, width: float, quotes: Quotes
) -> tuple[float, float, list[LegFill]] | None:
    """Shallowest strike whose entry vertical collects more than width/2.

    Starts at the ATM strike (which qualifies if it clears on its own) and
    steps ITM — down through calls for BEARISH, up through puts for BULLISH.
    Returns (strike, credit, legs), or None when no strike within
    HALFWIDTH_MAX_STEPS clears the threshold: the variant then takes no
    trade rather than falling back to a shallower strike.
    """
    strike = atm_strike(spot)
    step = -STRIKE_STEP if direction == "BEARISH" else STRIKE_STEP
    for _ in range(HALFWIDTH_MAX_STEPS):
        if direction == "BEARISH":
            priced = vertical_credit(quotes, strike, strike + width, "C")
        else:
            priced = vertical_credit(quotes, strike, strike - width, "P")
        if priced is not None and priced[0] > width / 2:
            return strike, priced[0], priced[1]
        strike += step
    return None


class ButterflySimulator:
    """Runs the variant grid against live chain snapshots and signals."""

    def __init__(
        self,
        variants: list[VariantConfig],
        event_sink: Callable[[dict], None] | None = None,
    ) -> None:
        self.variants = variants
        self.structures: list[Structure] = []
        self.event_sink = event_sink
        self.skipped_entries: int = 0

    def live_incomplete(
        self, variant: str, direction: str | None = None
    ) -> list[Structure]:
        return [
            s
            for s in self.structures
            if s.variant == variant
            and s.status == "OPEN"
            and (direction is None or s.direction == direction)
        ]

    def emit(
        self, kind: str, ts: datetime, structure: Structure, **extra: object
    ) -> None:
        record: dict = {
            "event": kind,
            "ts": ts.isoformat(),
            **asdict(structure),
            **extra,
        }
        logger.info(
            "%s %s %s K=%s w=%s pnl=%s",
            kind,
            structure.variant,
            structure.direction,
            structure.short_strike,
            structure.width,
            structure.pnl_points,
        )
        if self.event_sink:
            self.event_sink(record)

    def on_snapshot(
        self,
        ts: datetime,
        spot: float,
        quotes: Quotes,
        signals: list[TradeSignal],
        gate_ctx: dict[str, float | None] | None = None,
        regime_state: dict[str, float | None] | None = None,
    ) -> None:
        ts_et = ts.astimezone(ET)
        for variant in self.variants:
            routed = [s for s in signals if signal_matches(variant, s)]
            for signal in routed:
                if signal.signal_type == "OPEN":
                    self.try_enter(
                        variant, ts, spot, quotes, signal, gate_ctx, regime_state
                    )
                elif signal.signal_type == "CLOSE":
                    self.close_incomplete(
                        variant,
                        signal.direction,
                        ts,
                        quotes,
                        f"signal_{signal.trigger}",
                    )

            if ts_et.time() <= LAST_COMPLETION:
                self.try_complete(variant, ts, spot, quotes, regime_state)

            if ts_et.time() >= FORCED_CLOSE:
                for structure in self.live_incomplete(variant.name):
                    self.close_structure(structure, ts, quotes, "forced_eod")

    def entry_legs_for(
        self, direction: str, strike: float, width: float, quotes: Quotes
    ) -> tuple[float, list[LegFill]] | None:
        if direction == "BEARISH":
            return vertical_credit(quotes, strike, strike + width, "C")
        return vertical_credit(quotes, strike, strike - width, "P")

    def counter_credit_for(
        self, structure: Structure, quotes: Quotes
    ) -> tuple[float, list[LegFill]] | None:
        if structure.direction == "BEARISH":
            return vertical_credit(
                quotes,
                structure.short_strike,
                structure.short_strike - structure.width,
                "P",
            )
        return vertical_credit(
            quotes,
            structure.short_strike,
            structure.short_strike + structure.width,
            "C",
        )

    def try_enter(
        self,
        variant: VariantConfig,
        ts: datetime,
        spot: float,
        quotes: Quotes,
        signal: TradeSignal,
        gate_ctx: dict[str, float | None] | None = None,
        regime_state: dict[str, float | None] | None = None,
    ) -> None:
        if self.live_incomplete(variant.name, signal.direction):
            return
        ctx = gate_ctx or {}
        bucket = gate_bucket(ctx.get("hist_5m"), ctx.get("slope_5m"), signal.direction)
        if variant.gate_enforced and bucket not in GATED_BUCKETS:
            return  # enforced arm trades only imminent/near clusters
        if variant.strike_rule == "halfwidth":
            picked = halfwidth_entry(signal.direction, spot, variant.width, quotes)
            if picked is None:
                self.skipped_entries += 1
                logger.warning(
                    "Skipped entry %s %s — no strike clears width/2",
                    variant.name,
                    signal.direction,
                )
                return
            strike, credit, legs = picked
        else:
            strike = atm_strike(spot)
            priced = self.entry_legs_for(
                signal.direction, strike, variant.width, quotes
            )
            if priced is None or priced[0] <= 0:
                self.skipped_entries += 1
                logger.warning(
                    "Skipped entry %s %s K=%s — unusable quotes",
                    variant.name,
                    signal.direction,
                    strike,
                )
                return
            credit, legs = priced
        structure = Structure(
            variant=variant.name,
            direction=signal.direction,
            short_strike=strike,
            width=variant.width,
            opened_at=ts.isoformat(),
            entry_spot=spot,
            entry_credit=credit,
            entry_legs=legs,
            signal_trigger=signal.trigger,
            gate_bucket=bucket,
            gate_hist_5m=ctx.get("hist_5m"),
            gate_slope_5m=ctx.get("slope_5m"),
            gate_flip_eta_5m=ctx.get("flip_eta_5m"),
            gate_hist_1m=ctx.get("hist_1m"),
            gate_slope_1m=ctx.get("slope_1m"),
            gate_flip_eta_1m=ctx.get("flip_eta_1m"),
            regime_drive_entry=(regime_state or {}).get("drive_atr"),
            regime_retrace_entry=(regime_state or {}).get("retrace_frac"),
        )
        self.structures.append(structure)
        self.emit("ENTRY", ts, structure)

    def try_complete(
        self,
        variant: VariantConfig,
        ts: datetime,
        spot: float,
        quotes: Quotes,
        regime_state: dict[str, float | None] | None = None,
    ) -> None:
        for structure in self.live_incomplete(variant.name):
            priced = self.counter_credit_for(structure, quotes)
            if priced is None:
                continue
            counter, legs = priced
            total = structure.entry_credit + counter
            complete = total >= structure.width + variant.completion_margin
            early = False
            if not complete and variant.early_fly_adverse_pts is not None:
                # Early-fly conversion: at the adverse trigger, take the
                # counter side now — a bounded deficit with the tent kept,
                # instead of a realized stop.
                buyback = self.entry_legs_for(
                    structure.direction,
                    structure.short_strike,
                    structure.width,
                    quotes,
                )
                if (
                    buyback is not None
                    and buyback[0] - structure.entry_credit
                    >= variant.early_fly_adverse_pts
                ):
                    complete = True
                    early = True
            if complete:
                structure.status = "COMPLETED"
                structure.completed_at = ts.isoformat()
                structure.completion_spot = spot
                structure.completion_credit = counter
                structure.completion_legs = legs
                structure.regime_drive_completion = (regime_state or {}).get(
                    "drive_atr"
                )
                structure.regime_retrace_completion = (regime_state or {}).get(
                    "retrace_frac"
                )
                self.emit(
                    "COMPLETION",
                    ts,
                    structure,
                    total_credit=total,
                    locked_min_pnl=total - structure.width,
                    early_fly=early,
                )

    def close_incomplete(
        self,
        variant: VariantConfig,
        direction: str,
        ts: datetime,
        quotes: Quotes,
        reason: str,
    ) -> None:
        for structure in self.live_incomplete(variant.name, direction):
            self.close_structure(structure, ts, quotes, reason)

    def close_structure(
        self, structure: Structure, ts: datetime, quotes: Quotes, reason: str
    ) -> None:
        priced = self.entry_legs_for(
            structure.direction, structure.short_strike, structure.width, quotes
        )
        cost = priced[0] if priced is not None else None
        if cost is None:
            logger.warning(
                "Close without usable quotes: %s %s — P&L left unresolved",
                structure.variant,
                structure.direction,
            )
        structure.status = "CLOSED"
        structure.closed_at = ts.isoformat()
        structure.close_cost = cost
        structure.close_reason = reason
        structure.pnl_points = (
            structure.entry_credit - cost if cost is not None else None
        )
        self.emit("CLOSE", ts, structure)

    def settle(self, ts: datetime, settlement_spot: float) -> None:
        """Settle completed butterflies at the 16:00 SPX print."""
        for structure in self.structures:
            if structure.status != "COMPLETED":
                continue
            total = structure.entry_credit + (structure.completion_credit or 0.0)
            payoff = total - min(
                abs(settlement_spot - structure.short_strike), structure.width
            )
            structure.status = "SETTLED"
            structure.pnl_points = payoff
            self.emit("SETTLEMENT", ts, structure, settlement_spot=settlement_spot)

    def summary(self) -> dict:
        by_variant: dict[str, dict] = {}
        for variant in self.variants:
            rows = [s for s in self.structures if s.variant == variant.name]
            completed = [s for s in rows if s.status in ("COMPLETED", "SETTLED")]
            closed = [s for s in rows if s.status == "CLOSED"]
            by_variant[variant.name] = {
                "entries": len(rows),
                "completed": len(completed),
                "closed_incomplete": len(closed),
                "still_open": len([s for s in rows if s.status == "OPEN"]),
                "pnl_points": sum(s.pnl_points or 0.0 for s in rows),
                "completed_pnl": [s.pnl_points for s in completed],
                "closed_pnl": [s.pnl_points for s in closed],
            }
        return {
            "variants": by_variant,
            "skipped_entries": self.skipped_entries,
            "total_pnl_points": sum(s.pnl_points or 0.0 for s in self.structures),
        }


class JsonlEventSink:
    """Append simulator events to a JSONL file."""

    def __init__(self, path: str) -> None:
        self.path = path

    def __call__(self, record: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
