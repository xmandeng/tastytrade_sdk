"""Position metrics reader -- pure Redis consumer.

Reads positions, latest quotes, latest Greeks, and instrument details
from Redis HSET. Joins them via MetricsTracker into a DataFrame.
Provides strategy classification via StrategyClassifier.
No API calls, no socket connections.
"""

import json
import logging
import os
from decimal import Decimal
from typing import Any, Optional

import pandas as pd
import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.accounts.models import Position, TradeChain
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.accounts.transactions import EntryCredit
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
        self.entry_credit_records: dict[str, EntryCredit] = {}
        self.entry_credits: dict[str, Decimal] = {}
        self.trade_chains: dict[str, TradeChain] = {}

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
        return classifier.classify(
            self.tracker.securities,
            self.instruments,
            self.entry_credits or None,
        )

    @property
    def strategy_summary(self) -> pd.DataFrame:
        """Strategy summary DataFrame with Greeks, DTE, P&L, and health alerts."""
        classified = self.strategies
        if not classified:
            return pd.DataFrame(
                columns=[
                    "underlying",
                    "strategy",
                    "qty",
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

            # Extract common contract quantity from option legs
            option_legs = [leg for leg in strat.legs if leg.is_option]
            if option_legs:
                qty = int(option_legs[0].abs_quantity)
            else:
                qty = int(strat.legs[0].abs_quantity) if strat.legs else 0

            # Normalize delta to per-position (1x) scale
            raw_delta = strat.net_delta
            per_pos_delta = (
                round(raw_delta / qty, 2)
                if raw_delta is not None and qty > 0
                else raw_delta
            )

            # Direction sign only — no repeated quantity
            leg_desc = ", ".join(
                f"{'+' if leg.is_long else '-'}"
                f"{leg.option_type or leg.instrument_type.value}"
                f"{'@' + str(leg.strike.normalize()) if leg.strike else ''}"
                for leg in strat.legs
            )
            # -- TradeChain enrichment block (experimental) --
            # Match strategy to trade chain by underlying symbol + open entry legs.
            # Can be removed without side effects if enrichment proves unnecessary.
            chain_match = self.match_trade_chain(strat)
            if chain_match is not None:
                cd = chain_match.computed_data
                chain_fields = {
                    "rolls": cd.roll_count,
                    "realized_pnl": cd.realized_gain_with_fees,
                    "total_fees": cd.total_fees,
                    "opened_at": cd.opened_at,
                    "tt_strategy": chain_match.description,
                }
            else:
                chain_fields = {
                    "rolls": None,
                    "realized_pnl": None,
                    "total_fees": None,
                    "opened_at": None,
                    "tt_strategy": None,
                }
            # -- end TradeChain enrichment block --

            rows.append(
                {
                    "underlying": strat.underlying,
                    "strategy": strat.strategy_type.value,
                    "qty": qty,
                    "legs": leg_desc,
                    "net_delta": per_pos_delta,
                    "net_theta": strat.net_theta,
                    "net_vega": strat.net_vega,
                    "dte": strat.days_to_expiration,
                    "max_profit": f"{strat.max_profit:,}"
                    if strat.max_profit is not None
                    else None,
                    "max_loss": f"{strat.max_loss:,}"
                    if strat.max_loss is not None
                    else None,
                    "health": health_level,
                    "alerts": alert_str,
                    **chain_fields,
                }
            )
        df = pd.DataFrame(rows)
        if not df.empty and "dte" in df.columns:
            df["dte"] = df["dte"].astype("Int64")  # nullable integer dtype
            # -- TradeChain enrichment block (experimental) --
            if "rolls" in df.columns:
                df["rolls"] = df["rolls"].astype("Int64")
            # -- end TradeChain enrichment block --
        return df

    # -- TradeChain enrichment block (experimental) --
    # Matches a classified Strategy to a TradeChain by underlying symbol and
    # open entry leg symbols. Can be removed without side effects.
    def match_trade_chain(self, strategy: Strategy) -> Optional[TradeChain]:
        """Find the best-matching open TradeChain for a classified strategy.

        Matches purely on leg symbol overlap between the chain's open-entries
        and the strategy's legs. No underlying comparison needed — the leg
        symbols (full OCC / futures option symbols) are unique identifiers.
        Returns the chain with the highest overlap, or None if no match.
        """
        if not self.trade_chains:
            return None

        strat_symbols = {leg.symbol.strip() for leg in strategy.legs}
        best_chain: Optional[TradeChain] = None
        best_overlap = 0

        for chain in self.trade_chains.values():
            if not chain.computed_data.open:
                continue
            chain_symbols = {e.symbol.strip() for e in chain.computed_data.open_entries}
            overlap = len(strat_symbols & chain_symbols)
            if overlap > best_overlap:
                best_overlap = overlap
                best_chain = chain

        return best_chain

    # -- end TradeChain enrichment block --

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

        # 6. Read entry credits (transaction-derived dollar values)
        raw_credits = await self.redis.hgetall(AccountStreamPublisher.ENTRY_CREDITS_KEY)
        self.entry_credit_records = {}
        self.entry_credits = {}
        for key, value in raw_credits.items():
            try:
                symbol = key.decode() if isinstance(key, bytes) else key
                credit = EntryCredit.model_validate_json(value)
                self.entry_credit_records[symbol] = credit
                self.entry_credits[symbol] = credit.value
            except Exception as e:
                logger.debug("Skipped entry credit: %s", e)

        if self.entry_credits:
            logger.info("Loaded %d entry credits from Redis", len(self.entry_credits))

        # 7. Read trade chains (TT-80: OrderChain lifecycle data)
        # -- TradeChain enrichment block (experimental) --
        # This block reads trade chain data from Redis and indexes by underlying
        # symbol for join into strategy_summary. Can be removed without side effects
        # if the enrichment proves unnecessary.
        raw_chains = await self.redis.hgetall(AccountStreamPublisher.TRADE_CHAINS_KEY)
        self.trade_chains = {}
        for _key, value in raw_chains.items():
            try:
                chain = TradeChain.model_validate_json(value)
                self.trade_chains[chain.id] = chain
            except Exception as e:
                logger.debug("Skipped trade chain: %s", e)

        if self.trade_chains:
            logger.info("Loaded %d trade chains from Redis", len(self.trade_chains))
        # -- end TradeChain enrichment block --

        # 8. Enrich DataFrame with entry credit data (renumbered after trade chain step)
        df = tracker.df
        if not df.empty and self.entry_credit_records:
            records = self.entry_credit_records

            def get_entry_value(sym: str) -> float | None:
                rec = records.get(sym)
                return float(rec.value) if rec else None

            def get_entry_price(sym: str) -> float | None:
                rec = records.get(sym)
                if rec and rec.per_unit_price is not None:
                    return float(rec.per_unit_price)
                return None

            def get_fees(sym: str) -> float | None:
                rec = records.get(sym)
                return float(rec.fees) if rec else None

            df["entry_value"] = df["symbol"].map(get_entry_value)
            df["entry_price"] = df["symbol"].map(get_entry_price)
            df["fees"] = df["symbol"].map(get_fees)

        # 9. Enrich with DTE from instrument data
        if not df.empty and self.instruments:
            instruments = self.instruments

            def get_dte(sym: str) -> int | None:
                inst = instruments.get(sym)
                if inst and isinstance(inst, dict):
                    dte = inst.get("days-to-expiration")
                    return int(dte) if dte is not None else None
                return None

            df["dte"] = df["symbol"].map(get_dte).astype("Int64")

        self.position_metrics_df = df
        return self.position_metrics_df

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
