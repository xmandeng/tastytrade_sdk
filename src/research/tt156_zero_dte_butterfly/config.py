"""Run configuration for the TT-156 research day."""

from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# US equity market full-closure holidays (NYSE/Nasdaq). The weekday OS cron
# fires Mon-Fri and can't see holidays, so the collector self-skips these.
# Extend as the calendar rolls forward.
MARKET_HOLIDAYS = frozenset(
    {
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),  # Independence Day observed (Jul 4 is a Saturday)
        date(2026, 9, 7),  # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    }
)


def is_trading_day(day: date) -> bool:
    """True if the market is open: a weekday that is not a full-closure holiday."""
    return day.weekday() < 5 and day not in MARKET_HOLIDAYS


SYMBOL = "SPX"
OPTION_ROOT = "SPXW"
STRIKE_STEP = 5.0
CONTRACT_MULTIPLIER = 100

SESSION_START = time(9, 28)
MARKET_OPEN = time(9, 30)
LAST_ENTRY = time(14, 30)
FORCED_CLOSE = time(15, 45)
LAST_COMPLETION = time(15, 55)
MARKET_CLOSE = time(16, 0)
SESSION_END = time(16, 15)

# Half-width credit strike rule: the entry vertical must collect MORE than
# width/2 at mid, selling the shallowest ITM strike that clears it (the ATM
# strike qualifies if it clears on its own). Search depth is capped well above
# anything observed — the 36-session retro replay never needed more than 7
# steps (35 pts) to find a qualifying strike.
HALFWIDTH_MAX_STEPS = 30

# Flip-ETA gate thresholds (sealed 5m bars until the MACD histogram crosses
# zero). Fixed by the 2026-08 research finding (TT-156 comment 15851): entries
# fired while the 5m MACD opposes the direction but is within NEAR bars of
# flipping were the only profitable subset, in-sample and in the 16-month
# candle replay. Deliberately constants, not tunables.
GATE_ETA_IMMINENT = 3.0
GATE_ETA_NEAR = 10.0


@dataclass(frozen=True)
class VariantConfig:
    """One paper-trading strategy variant.

    direction of entry comes from the signal; the variant fixes structure
    geometry and the completion threshold.
    """

    name: str
    width: float
    signal_interval: str  # dxlink interval suffix: "m" or "5m"
    completion_margin: float  # extra credit (points) required beyond width
    strike_rule: str = "atm"  # "atm" | "halfwidth" (entry credit > width/2)

    @property
    def signal_symbol(self) -> str:
        return f"{SYMBOL}{{={self.signal_interval}}}"


def default_variants() -> list[VariantConfig]:
    variants: list[VariantConfig] = []
    for width in (10.0, 25.0, 50.0):
        for interval in ("m", "5m"):
            for margin in (0.0, 2.0):
                for rule in ("atm", "halfwidth"):
                    suffix = "_hw" if rule == "halfwidth" else ""
                    variants.append(
                        VariantConfig(
                            name=f"w{width:g}_{interval}_m{margin:g}{suffix}",
                            width=width,
                            signal_interval=interval,
                            completion_margin=margin,
                            strike_rule=rule,
                        )
                    )
    return variants


@dataclass
class RunConfig:
    """Collector run parameters."""

    data_dir: Path
    cadence_seconds: float = 15.0
    strike_window: float = 160.0  # points either side of spot
    recenter_buffer: float = (
        40.0  # re-resolve chain when spot drifts this close to edge
    )
    warmup_days: int = 3
    variants: list[VariantConfig] = field(default_factory=default_variants)
    # Only act on closed Hull/MACD candles: buffer the forming bar from the
    # live feed and forward it to the engine only once a newer bar arrives, so
    # no trade is taken before a full candle establishes the signal. Eliminates
    # the intra-candle whipsaws (TT-156 days 1-3 churn analysis).
    confirm_on_close: bool = True
    max_cycles: int | None = None  # test mode: stop after N cycles
    ignore_session_times: bool = False  # test mode: run regardless of clock
