"""Strategy health monitoring with configurable TOML thresholds."""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from tastytrade.analytics.strategies.models import Strategy, StrategyType

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "strategy_health.toml"
)


class AlertLevel(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HealthThresholds:
    """Configurable thresholds for strategy health checks."""

    dte_warning: int = 14
    dte_critical: int = 7
    max_loss_warning: float = 0.75
    max_loss_critical: float = 0.90
    delta_drift_warning: float = 0.30


@dataclass(frozen=True)
class HealthAlert:
    """A single health alert for a strategy."""

    strategy: Strategy
    level: AlertLevel
    message: str


class StrategyHealthMonitor:
    """Monitors strategy health against configurable thresholds."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.thresholds_map: dict[str, HealthThresholds] = {}
        self.default_thresholds = HealthThresholds()
        self.load_config()

    def load_config(self) -> None:
        """Load thresholds from TOML config file."""
        if not self.config_path.exists():
            logger.warning(
                "Health config not found at %s, using defaults", self.config_path
            )
            return

        with open(self.config_path, "rb") as f:
            config = tomllib.load(f)

        # Load default section
        default_section = config.get("default", {})
        self.default_thresholds = HealthThresholds(
            dte_warning=default_section.get("dte_warning", 14),
            dte_critical=default_section.get("dte_critical", 7),
            max_loss_warning=default_section.get("max_loss_warning", 0.75),
            max_loss_critical=default_section.get("max_loss_critical", 0.90),
            delta_drift_warning=default_section.get("delta_drift_warning", 0.30),
        )

        # Load per-strategy-type overrides
        for key, section in config.items():
            if key == "default":
                continue
            self.thresholds_map[key] = HealthThresholds(
                dte_warning=section.get(
                    "dte_warning", self.default_thresholds.dte_warning
                ),
                dte_critical=section.get(
                    "dte_critical", self.default_thresholds.dte_critical
                ),
                max_loss_warning=section.get(
                    "max_loss_warning", self.default_thresholds.max_loss_warning
                ),
                max_loss_critical=section.get(
                    "max_loss_critical", self.default_thresholds.max_loss_critical
                ),
                delta_drift_warning=section.get(
                    "delta_drift_warning",
                    self.default_thresholds.delta_drift_warning,
                ),
            )

        logger.info(
            "Loaded health config: %d strategy-specific overrides",
            len(self.thresholds_map),
        )

    def thresholds_for(self, strategy_type: StrategyType) -> HealthThresholds:
        """Get thresholds for a strategy type, falling back to defaults."""
        key = strategy_type.name.lower()
        return self.thresholds_map.get(key, self.default_thresholds)

    def check(self, strategy: Strategy) -> list[HealthAlert]:
        """Check a single strategy's health."""
        alerts: list[HealthAlert] = []
        thresholds = self.thresholds_for(strategy.strategy_type)

        # DTE check
        dte = strategy.days_to_expiration
        if dte is not None:
            if dte <= thresholds.dte_critical:
                alerts.append(
                    HealthAlert(
                        strategy=strategy,
                        level=AlertLevel.CRITICAL,
                        message=f"DTE={dte} <= {thresholds.dte_critical}",
                    )
                )
            elif dte <= thresholds.dte_warning:
                alerts.append(
                    HealthAlert(
                        strategy=strategy,
                        level=AlertLevel.WARNING,
                        message=f"DTE={dte} <= {thresholds.dte_warning}",
                    )
                )

        # Delta drift check — skip for delta-1 and covered strategies
        # where high absolute delta is inherent, not a risk signal.
        delta_exempt = {
            StrategyType.LONG_STOCK,
            StrategyType.SHORT_STOCK,
            StrategyType.LONG_CRYPTO,
            StrategyType.SHORT_CRYPTO,
            StrategyType.LONG_FUTURE,
            StrategyType.SHORT_FUTURE,
            StrategyType.COVERED_CALL,
            StrategyType.PROTECTIVE_PUT,
        }
        net_delta = strategy.net_delta
        if net_delta is not None and strategy.strategy_type not in delta_exempt:
            # Normalize to per-position (1x) delta for threshold comparison
            option_legs = [leg for leg in strategy.legs if leg.is_option]
            qty = (
                int(option_legs[0].abs_quantity)
                if option_legs
                else int(strategy.legs[0].abs_quantity)
                if strategy.legs
                else 1
            )
            per_pos_delta = net_delta / qty if qty > 0 else net_delta
            if abs(per_pos_delta) > thresholds.delta_drift_warning:
                alerts.append(
                    HealthAlert(
                        strategy=strategy,
                        level=AlertLevel.WARNING,
                        message=(
                            f"Net delta={per_pos_delta:.2f} exceeds "
                            f"+/-{thresholds.delta_drift_warning}"
                        ),
                    )
                )

        # Max loss proximity check
        max_loss = strategy.max_loss
        max_profit = strategy.max_profit
        if max_loss is not None and max_profit is not None and max_loss > 0:
            # Simplified check -- full implementation requires current P&L tracking
            pass

        return alerts

    def check_all(self, strategies: list[Strategy]) -> list[HealthAlert]:
        """Check health of all strategies."""
        alerts: list[HealthAlert] = []
        for strategy in strategies:
            alerts.extend(self.check(strategy))
        return alerts
