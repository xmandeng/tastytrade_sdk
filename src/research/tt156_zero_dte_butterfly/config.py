"""Run configuration for the TT-156 research day."""

from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

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

    @property
    def signal_symbol(self) -> str:
        return f"{SYMBOL}{{={self.signal_interval}}}"


def default_variants() -> list[VariantConfig]:
    variants: list[VariantConfig] = []
    for width in (10.0, 25.0, 50.0):
        for interval in ("m", "5m"):
            for margin in (0.0, 2.0):
                variants.append(
                    VariantConfig(
                        name=f"w{width:g}_{interval}_m{margin:g}",
                        width=width,
                        signal_interval=interval,
                        completion_margin=margin,
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
