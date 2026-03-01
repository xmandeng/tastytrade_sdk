"""Position metrics reader -- pure Redis consumer.

Reads positions, latest quotes, latest Greeks, and instrument details
from Redis HSET. Joins them via MetricsTracker into a DataFrame.
Provides strategy classification via StrategyClassifier.
No API calls, no socket connections.
"""

import json
import logging
import os
from typing import Any, Optional

import pandas as pd
import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.accounts.models import Position
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.analytics.metrics import MetricsTracker
from tastytrade.analytics.strategies.classifier import StrategyClassifier
from tastytrade.analytics.strategies.health import StrategyHealthMonitor
from tastytrade.analytics.strategies.models import Strategy
from tastytrade.messaging.models.events import GreeksEvent, QuoteEvent

logger = logging.getLogger(__name__)


class PositionMetricsReader:
    """Reads position metrics from Redis. Pure consumer -- no connections."""

    QUOTES_KEY = "tastytrade:latest:QuoteEvent"
    GREEKS_KEY = "tastytrade:latest:GreeksEvent"

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        port = redis_port or int(os.environ.get("REDIS_PORT", "6379"))
        self.redis = aioredis.Redis(host=host, port=port)  # type: ignore[arg-type]
        self.position_metrics_df: pd.DataFrame = pd.DataFrame()
        self.tracker: Optional[MetricsTracker] = None
        self.instruments: dict[str, Any] = {}

    @property
    def summary(self) -> pd.DataFrame:
        """Aggregate positions by underlying: net delta, leg count, leg descriptions."""
        if self.position_metrics_df.empty:
            return pd.DataFrame(
                columns=["underlying_symbol", "net_delta", "num_legs", "legs"]
            )

        rows = []
        for underlying, group in self.position_metrics_df.groupby("underlying_symbol"):
            legs = []
            net_delta = 0.0
            for _, row in group.iterrows():
                direction = str(row.get("quantity_direction", ""))
                qty = row.get("quantity", 0)
                inst_type = str(row.get("instrument_type", ""))
                delta = row.get("delta")
                if pd.notna(delta):
                    net_delta += float(delta) * float(qty)  # type: ignore[arg-type]
                legs.append(f"{qty}x {direction} {inst_type}")
            rows.append(
                {
                    "underlying_symbol": underlying,
                    "net_delta": round(net_delta, 2),
                    "num_legs": len(group),
                    "legs": ", ".join(legs),
                }
            )
        return pd.DataFrame(rows)

    @property
    def strategies(self) -> list[Strategy]:
        """Classify positions into named option strategies."""
        if self.tracker is None:
            return []
        classifier = StrategyClassifier()
        return classifier.classify(self.tracker.securities, self.instruments)

    @property
    def strategy_summary(self) -> pd.DataFrame:
        """Strategy summary DataFrame with Greeks, DTE, P&L, and health alerts."""
        classified = self.strategies
        if not classified:
            return pd.DataFrame(
                columns=[
                    "underlying",
                    "strategy",
                    "legs",
                    "net_delta",
                    "net_theta",
                    "net_vega",
                    "dte",
                    "max_profit",
                    "max_loss",
                    "health",
                ]
            )

        monitor = StrategyHealthMonitor()
        rows = []
        for strat in classified:
            alerts = monitor.check(strat)
            alert_str = "; ".join(a.message for a in alerts) if alerts else "OK"
            health_level = max(a.level.value for a in alerts) if alerts else "OK"
            leg_desc = ", ".join(
                f"{leg.signed_quantity:+g}x {leg.option_type or leg.instrument_type.value}"
                f"{'@' + str(leg.strike) if leg.strike else ''}"
                for leg in strat.legs
            )
            rows.append(
                {
                    "underlying": strat.underlying,
                    "strategy": strat.strategy_type.value,
                    "legs": leg_desc,
                    "net_delta": strat.net_delta,
                    "net_theta": strat.net_theta,
                    "net_vega": strat.net_vega,
                    "dte": strat.days_to_expiration,
                    "max_profit": strat.max_profit,
                    "max_loss": strat.max_loss,
                    "health": health_level,
                    "alerts": alert_str,
                }
            )
        df = pd.DataFrame(rows)
        if not df.empty and "dte" in df.columns:
            df["dte"] = df["dte"].astype("Int64")  # nullable integer dtype
        return df

    async def read(self) -> pd.DataFrame:
        """Read positions + market data + instruments from Redis, return joined DataFrame."""
        # 1. Read positions
        raw_positions = await self.redis.hgetall(AccountStreamPublisher.POSITIONS_KEY)
        if not raw_positions:
            return MetricsTracker().df

        positions = []
        for _key, value in raw_positions.items():
            try:
                positions.append(Position.model_validate(json.loads(value)))
            except Exception as e:
                logger.warning("Failed to parse position: %s", e)

        # 2. Load into tracker
        tracker = MetricsTracker()
        tracker.load_positions(positions)
        self.tracker = tracker

        # 3. Read latest quotes
        raw_quotes = await self.redis.hgetall(self.QUOTES_KEY)
        for _key, value in raw_quotes.items():
            try:
                quote = QuoteEvent.model_validate(json.loads(value))
                tracker.on_quote_event(quote)
            except Exception as e:
                logger.debug("Skipped quote: %s", e)

        # 4. Read latest Greeks
        raw_greeks = await self.redis.hgetall(self.GREEKS_KEY)
        for _key, value in raw_greeks.items():
            try:
                greeks = GreeksEvent.model_validate(json.loads(value))
                tracker.on_greeks_event(greeks)
            except Exception as e:
                logger.debug("Skipped greeks: %s", e)

        # 5. Read instrument details
        raw_instruments = await self.redis.hgetall(
            AccountStreamPublisher.INSTRUMENTS_KEY
        )
        self.instruments = {}
        for key, value in raw_instruments.items():
            try:
                symbol = key.decode() if isinstance(key, bytes) else key
                self.instruments[symbol] = json.loads(value)
            except Exception as e:
                logger.debug("Skipped instrument: %s", e)

        if self.instruments:
            logger.info("Loaded %d instruments from Redis", len(self.instruments))

        self.position_metrics_df = tracker.df
        return self.position_metrics_df

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
