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
# Hull-only forward-test entry window (Basics v2, 2026-08-27): the first
# half hour is churn (user rule predating this harness, re-confirmed on the
# 50-session clean replay) and late entries lack time to complete the fly.
HULL_ENTRY_START = time(10, 0)
HULL_ENTRY_END = time(14, 0)
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

# First-entry filter (calibrated 2026-08-27 on 200 5m-family trades): only the
# first 5m-strategy cluster in any rolling window is "on-strategy"; re-entries
# within the window lost at every width. Frozen calibration, not a tunable.
FIRST_ENTRY_WINDOW_MIN = 90


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
    gate_enforced: bool = False  # only enter imminent/near flip-ETA clusters

    @property
    def signal_symbol(self) -> str:
        return f"{SYMBOL}{{={self.signal_interval}}}"


def default_variants() -> list[VariantConfig]:
    """The forward-test grid (Basics v2, 2026-08-27): hull-only 5m signals,
    25-wide primary + 50-wide tracked. The old 30-variant MACD/gate/half-width
    grid was retired with the clean-slate directive — those arms were
    calibrated against the lagged feed (TT-157) and are void."""
    return [
        VariantConfig(
            name="w25_5m_m0",
            width=25.0,
            signal_interval="5m",
            completion_margin=0.0,
        ),
        # Tracked arm (user-approved 2026-08-27): +1 pt minimum extra credit
        # before locking the fly — the E1 refinement hump; earns forward
        # evidence alongside m0 before it can touch the primary rule.
        VariantConfig(
            name="w25_5m_m1",
            width=25.0,
            signal_interval="5m",
            completion_margin=1.0,
        ),
        VariantConfig(
            name="w50_5m_m0",
            width=50.0,
            signal_interval="5m",
            completion_margin=0.0,
        ),
    ]


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
