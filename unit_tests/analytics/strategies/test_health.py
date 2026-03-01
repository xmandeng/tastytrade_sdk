"""Unit tests for StrategyHealthMonitor."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tastytrade.accounts.models import InstrumentType
from tastytrade.analytics.strategies.health import (
    AlertLevel,
    HealthThresholds,
    StrategyHealthMonitor,
)
from tastytrade.analytics.strategies.models import ParsedLeg, Strategy, StrategyType


def make_strategy(
    strategy_type: StrategyType = StrategyType.SHORT_STRANGLE,
    underlying: str = "SPY",
    legs: tuple[ParsedLeg, ...] | None = None,
) -> Strategy:
    """Create a Strategy with sane defaults for testing."""
    if legs is None:
        legs = (
            ParsedLeg(
                streamer_symbol=".SPYC310",
                symbol="SPY  260320C00310000",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="C",
                strike=Decimal("310"),
                expiration=date(2026, 3, 20),
                days_to_expiration=30,
                delta=0.15,
                theta=-0.05,
                mid_price=3.0,
            ),
            ParsedLeg(
                streamer_symbol=".SPYP290",
                symbol="SPY  260320P00290000",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="P",
                strike=Decimal("290"),
                expiration=date(2026, 3, 20),
                days_to_expiration=30,
                delta=-0.15,
                theta=-0.05,
                mid_price=2.5,
            ),
        )
    return Strategy(strategy_type=strategy_type, underlying=underlying, legs=legs)


class TestHealthThresholds:
    def test_defaults(self):
        t = HealthThresholds()
        assert t.dte_warning == 21
        assert t.dte_critical == 7
        assert t.max_loss_warning == 0.75
        assert t.max_loss_critical == 0.90
        assert t.delta_drift_warning == 0.30

    def test_frozen(self):
        t = HealthThresholds()
        with pytest.raises(AttributeError):
            t.dte_warning = 10  # type: ignore[misc]


class TestStrategyHealthMonitor:
    def test_load_default_config(self):
        """Monitor loads the project TOML config successfully."""
        monitor = StrategyHealthMonitor()
        assert monitor.default_thresholds.dte_warning == 21
        assert "iron_condor" in monitor.thresholds_map
        assert "short_strangle" in monitor.thresholds_map
        assert "jade_lizard" in monitor.thresholds_map

    def test_thresholds_for_known_type(self):
        monitor = StrategyHealthMonitor()
        t = monitor.thresholds_for(StrategyType.IRON_CONDOR)
        assert t.dte_warning == 30
        assert t.dte_critical == 14
        assert t.delta_drift_warning == 0.20

    def test_thresholds_for_unknown_type_falls_back_to_default(self):
        monitor = StrategyHealthMonitor()
        t = monitor.thresholds_for(StrategyType.CUSTOM)
        assert t == monitor.default_thresholds

    def test_missing_config_uses_defaults(self):
        monitor = StrategyHealthMonitor(config_path=Path("/nonexistent/config.toml"))
        assert monitor.default_thresholds == HealthThresholds()
        assert monitor.thresholds_map == {}

    def test_custom_config(self):
        toml_content = b"""
[default]
dte_warning = 15
dte_critical = 5
delta_drift_warning = 0.50

[short_strangle]
dte_warning = 20
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            monitor = StrategyHealthMonitor(config_path=Path(f.name))

        assert monitor.default_thresholds.dte_warning == 15
        assert monitor.default_thresholds.dte_critical == 5
        assert monitor.default_thresholds.delta_drift_warning == 0.50

        t = monitor.thresholds_for(StrategyType.SHORT_STRANGLE)
        assert t.dte_warning == 20
        assert t.dte_critical == 5  # inherited from default


class TestHealthChecks:
    def test_no_alerts_healthy(self):
        """Strategy with good DTE and small delta → no alerts."""
        strategy = make_strategy()
        monitor = StrategyHealthMonitor()
        alerts = monitor.check(strategy)
        assert len(alerts) == 0

    def test_dte_warning(self):
        """DTE between critical and warning → WARNING alert."""
        legs = (
            ParsedLeg(
                streamer_symbol=".SPYC310",
                symbol="SPY  C310",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="C",
                strike=Decimal("310"),
                expiration=date(2026, 3, 20),
                days_to_expiration=15,
                delta=0.10,
            ),
        )
        strategy = make_strategy(
            strategy_type=StrategyType.SHORT_STRANGLE,
            legs=legs,
        )
        monitor = StrategyHealthMonitor()
        # default dte_warning=21 for unspecified, but short_strangle has dte_warning=25
        alerts = monitor.check(strategy)
        dte_alerts = [a for a in alerts if "DTE" in a.message]
        assert len(dte_alerts) == 1
        assert dte_alerts[0].level == AlertLevel.WARNING

    def test_dte_critical(self):
        """DTE below critical threshold → CRITICAL alert."""
        legs = (
            ParsedLeg(
                streamer_symbol=".SPYC310",
                symbol="SPY  C310",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="C",
                strike=Decimal("310"),
                expiration=date(2026, 3, 20),
                days_to_expiration=3,
                delta=0.10,
            ),
        )
        strategy = make_strategy(
            strategy_type=StrategyType.NAKED_CALL,
            legs=legs,
        )
        monitor = StrategyHealthMonitor()
        alerts = monitor.check(strategy)
        dte_alerts = [a for a in alerts if "DTE" in a.message]
        assert len(dte_alerts) == 1
        assert dte_alerts[0].level == AlertLevel.CRITICAL

    def test_delta_drift_warning(self):
        """High net delta triggers delta drift warning."""
        legs = (
            ParsedLeg(
                streamer_symbol=".SPYC310",
                symbol="SPY  C310",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="C",
                strike=Decimal("310"),
                expiration=date(2026, 3, 20),
                days_to_expiration=30,
                delta=-0.50,
            ),
        )
        strategy = make_strategy(
            strategy_type=StrategyType.NAKED_CALL,
            legs=legs,
        )
        monitor = StrategyHealthMonitor()
        alerts = monitor.check(strategy)
        delta_alerts = [a for a in alerts if "delta" in a.message.lower()]
        assert len(delta_alerts) == 1
        assert delta_alerts[0].level == AlertLevel.WARNING

    def test_no_delta_alert_when_none(self):
        """Strategy with no delta data → no delta alert."""
        legs = (
            ParsedLeg(
                streamer_symbol=".SPYC310",
                symbol="SPY  C310",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="C",
                strike=Decimal("310"),
                expiration=date(2026, 3, 20),
                days_to_expiration=30,
                delta=None,
            ),
        )
        strategy = make_strategy(legs=legs)
        monitor = StrategyHealthMonitor()
        alerts = monitor.check(strategy)
        delta_alerts = [a for a in alerts if "delta" in a.message.lower()]
        assert len(delta_alerts) == 0

    def test_check_all(self):
        """check_all aggregates alerts from multiple strategies."""
        # Strategy 1: healthy
        s1 = make_strategy()
        # Strategy 2: critical DTE
        legs2 = (
            ParsedLeg(
                streamer_symbol=".SPYC310",
                symbol="SPY  C310",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="C",
                strike=Decimal("310"),
                expiration=date(2026, 3, 20),
                days_to_expiration=3,
                delta=0.05,
            ),
        )
        s2 = make_strategy(strategy_type=StrategyType.NAKED_CALL, legs=legs2)

        monitor = StrategyHealthMonitor()
        all_alerts = monitor.check_all([s1, s2])
        assert len(all_alerts) >= 1

    def test_iron_condor_specific_thresholds(self):
        """Iron condor uses its custom thresholds from TOML."""
        legs = (
            ParsedLeg(
                streamer_symbol=".SPYP280",
                symbol="SPY  P280",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=1,
                option_type="P",
                strike=Decimal("280"),
                expiration=date(2026, 3, 20),
                days_to_expiration=25,
                delta=-0.05,
            ),
            ParsedLeg(
                streamer_symbol=".SPYP290",
                symbol="SPY  P290",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="P",
                strike=Decimal("290"),
                expiration=date(2026, 3, 20),
                days_to_expiration=25,
                delta=-0.15,
            ),
            ParsedLeg(
                streamer_symbol=".SPYC310",
                symbol="SPY  C310",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=-1,
                option_type="C",
                strike=Decimal("310"),
                expiration=date(2026, 3, 20),
                days_to_expiration=25,
                delta=0.15,
            ),
            ParsedLeg(
                streamer_symbol=".SPYC320",
                symbol="SPY  C320",
                underlying="SPY",
                instrument_type=InstrumentType.EQUITY_OPTION,
                signed_quantity=1,
                option_type="C",
                strike=Decimal("320"),
                expiration=date(2026, 3, 20),
                days_to_expiration=25,
                delta=0.05,
            ),
        )
        strategy = make_strategy(
            strategy_type=StrategyType.IRON_CONDOR,
            legs=legs,
        )
        monitor = StrategyHealthMonitor()
        alerts = monitor.check(strategy)

        # Iron condor has dte_warning=30, so DTE=25 should trigger warning
        dte_alerts = [a for a in alerts if "DTE" in a.message]
        assert len(dte_alerts) == 1
        assert dte_alerts[0].level == AlertLevel.WARNING
