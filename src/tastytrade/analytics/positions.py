"""Position metrics reader -- pure Redis consumer.

Reads positions, latest quotes, latest Greeks, and instrument details
from Redis HSET. Joins them via MetricsTracker into a DataFrame.
Provides strategy classification via StrategyClassifier.
No API calls, no socket connections.
"""

import json
import logging
import os
import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import pandas as pd
import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.accounts.models import Position, QuantityDirection, TradeChain
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.accounts.transactions import EntryCredit
from tastytrade.analytics.metrics import MetricsTracker
from tastytrade.analytics.strategies.classifier import StrategyClassifier
from tastytrade.analytics.strategies.health import StrategyHealthMonitor
from tastytrade.analytics.strategies.models import Strategy
from tastytrade.messaging.models.events import GreeksEvent, QuoteEvent

logger = logging.getLogger(__name__)


def apply_effect(amount: Optional[str], effect: Optional[str]) -> Decimal:
    """Convert TastyTrade unsigned amount + effect string to signed Decimal.

    TastyTrade encodes sign via a separate effect field:
    'Credit' = positive (money received), 'Debit' = negative (money paid).
    """
    if amount is None:
        return Decimal("0")
    val = Decimal(amount)
    if effect == "Debit":
        return -val
    return val


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
                    "tt_strategy",
                ]
            )

        # Build symbol → tt_strategy lookup from positions DataFrame
        # so we can show TastyTrade's original classification alongside ours
        tt_strategy_by_symbol: dict[str, str] = {}
        if (
            not self.position_metrics_df.empty
            and "tt_strategy" in self.position_metrics_df.columns
        ):
            for _, row in self.position_metrics_df.iterrows():
                val = row.get("tt_strategy")
                if pd.notna(val):
                    tt_strategy_by_symbol[row["symbol"]] = str(val)

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
            # Look up TastyTrade's classification from any leg in this strategy
            tt_strat = None
            for leg in strat.legs:
                tt_strat = tt_strategy_by_symbol.get(leg.symbol)
                if tt_strat:
                    break

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
                    "tt_strategy": tt_strat,
                }
            )
        df = pd.DataFrame(rows)
        if not df.empty:
            if "dte" in df.columns:
                df["dte"] = df["dte"].astype("Int64")  # nullable integer dtype
            df = df.sort_values("underlying").reset_index(drop=True)
        dash_cols = [
            "net_delta",
            "net_theta",
            "net_vega",
            "dte",
            "max_profit",
            "max_loss",
        ]
        for col in dash_cols:
            if col in df.columns:
                df[col] = df[col].astype(object).fillna("-")
        return df

    # -- TradeChain enrichment block (experimental) --
    # Standalone view of trade chain lifecycle data. Each row is one chain
    # with its strategy name, P&L, fees, rolls, and open legs.
    # Can be removed without side effects.
    @property
    def chain_summary(self) -> pd.DataFrame:
        """Trade chain lifecycle summary — one row per OrderChain."""
        if not self.trade_chains:
            return pd.DataFrame(
                columns=[
                    "chain_id",
                    "underlying",
                    "tt_strategy",
                    "status",
                    "rolls",
                    "realized_pnl",
                    "total_fees",
                    "opened_at",
                    "legs",
                ]
            )

        rows = []
        for chain in self.trade_chains.values():
            cd = chain.computed_data
            status = "open" if cd.open else "closed"

            # Summarize open legs from open-entries
            leg_parts = []
            for entry in cd.open_entries:
                direction = "-" if entry.quantity_type == "Short" else "+"
                leg_parts.append(f"{direction}{entry.quantity}x {entry.symbol.strip()}")
            legs_str = ", ".join(leg_parts) if leg_parts else ""

            rows.append(
                {
                    "chain_id": chain.id,
                    "underlying": chain.underlying_symbol,
                    "tt_strategy": chain.description,
                    "status": status,
                    "rolls": cd.roll_count,
                    "realized_pnl": cd.realized_gain_with_fees,
                    "total_fees": cd.total_fees,
                    "opened_at": cd.opened_at,
                    "legs": legs_str,
                }
            )

        df = pd.DataFrame(rows)
        if not df.empty:
            df["rolls"] = df["rolls"].astype("Int64")
        return df

    # -- Campaign P&L aggregation (TT-91) --
    # Groups chains by underlying, sums realized P&L from rolls,
    # cross-references open legs with live position mark data.

    @property
    def campaign_summary(self) -> pd.DataFrame:
        """Campaign P&L by underlying — aggregates chains and open mark values."""
        columns = [
            "underlying",
            "chains",
            "open_chains",
            "total_rolls",
            "realized_pnl",
            "total_fees",
            "unrealized_mark",
            "net_pnl",
            "recovery_needed",
        ]
        if not self.trade_chains:
            return pd.DataFrame(columns=columns)

        # Build symbol → position lookup for mark value computation
        pos_by_symbol: dict[str, dict[str, Any]] = {}
        if not self.position_metrics_df.empty:
            for _, row in self.position_metrics_df.iterrows():
                pos_by_symbol[str(row["symbol"]).strip()] = {
                    "mid_price": row.get("mid_price"),
                    "quantity": row.get("quantity"),
                    "multiplier": row.get("multiplier"),
                    "quantity_direction": row.get("quantity_direction"),
                }

        # Group chains by underlying
        by_underlying: dict[str, list[TradeChain]] = {}
        for chain in self.trade_chains.values():
            by_underlying.setdefault(chain.underlying_symbol, []).append(chain)

        rows = []
        for underlying, chains in sorted(by_underlying.items()):
            total_realized = Decimal("0")
            total_fees = Decimal("0")
            total_rolls = 0
            open_chains = 0
            total_unrealized = Decimal("0")

            for chain in chains:
                cd = chain.computed_data
                total_realized += apply_effect(
                    cd.realized_gain, cd.realized_gain_effect
                )
                total_fees += Decimal(cd.total_fees) if cd.total_fees else Decimal("0")
                total_rolls += cd.roll_count

                if cd.open:
                    open_chains += 1
                    for entry in cd.open_entries:
                        sym = entry.symbol.strip()
                        pos = pos_by_symbol.get(sym)
                        if pos is None or pos["mid_price"] is None:
                            continue
                        mid = Decimal(str(pos["mid_price"]))
                        qty = Decimal(str(pos["quantity"]))
                        mult = Decimal(str(pos["multiplier"] or 1))
                        sign = (
                            Decimal("-1")
                            if str(pos["quantity_direction"]) == "Short"
                            or str(pos["quantity_direction"])
                            == "QuantityDirection.SHORT"
                            else Decimal("1")
                        )
                        total_unrealized += mid * qty * mult * sign

            net_pnl = total_realized + total_unrealized
            recovery = max(Decimal("0"), -net_pnl)

            rows.append(
                {
                    "underlying": underlying,
                    "chains": len(chains),
                    "open_chains": open_chains,
                    "total_rolls": total_rolls,
                    "realized_pnl": float(total_realized),
                    "total_fees": float(total_fees),
                    "unrealized_mark": float(total_unrealized),
                    "net_pnl": float(net_pnl),
                    "recovery_needed": float(recovery),
                }
            )

        df = pd.DataFrame(rows)
        if not df.empty:
            for col in ("chains", "open_chains", "total_rolls"):
                df[col] = df[col].astype("Int64")
            for col in (
                "realized_pnl",
                "total_fees",
                "unrealized_mark",
                "net_pnl",
                "recovery_needed",
            ):
                df[col] = df[col].round(2)
        return df

    def campaign_detail(self, underlying: Optional[str] = None) -> list[dict[str, Any]]:
        """Detailed roll history per chain, optionally filtered by underlying."""
        # Build symbol → position lookup for open leg mark values
        pos_by_symbol: dict[str, dict[str, Any]] = {}
        if not self.position_metrics_df.empty:
            for _, row in self.position_metrics_df.iterrows():
                pos_by_symbol[str(row["symbol"]).strip()] = {
                    "mid_price": row.get("mid_price"),
                    "quantity": row.get("quantity"),
                    "multiplier": row.get("multiplier"),
                    "quantity_direction": row.get("quantity_direction"),
                }

        results: list[dict[str, Any]] = []
        for chain in self.trade_chains.values():
            if underlying and chain.underlying_symbol != underlying:
                continue

            cd = chain.computed_data
            realized = apply_effect(cd.realized_gain, cd.realized_gain_effect)
            fees = Decimal(cd.total_fees) if cd.total_fees else Decimal("0")

            # Expand lite_nodes into readable history
            nodes = []
            for node in chain.lite_nodes:
                fill_cost = apply_effect(
                    node.total_fill_cost, node.total_fill_cost_effect
                )
                node_fees = (
                    Decimal(node.total_fees) if node.total_fees else Decimal("0")
                )

                legs = []
                for leg in node.legs:
                    legs.append(
                        {
                            "symbol": leg.symbol,
                            "action": leg.action,
                            "fill_quantity": leg.fill_quantity,
                        }
                    )

                entries = []
                for entry in node.entries:
                    direction = "Short" if entry.quantity_type == "Short" else "Long"
                    entries.append(
                        {
                            "symbol": entry.symbol.strip(),
                            "quantity": entry.quantity,
                            "direction": direction,
                        }
                    )

                snapshot: dict[str, Any] | None = None
                if node.market_state_snapshot:
                    ms = node.market_state_snapshot
                    snapshot = {
                        "total_delta": ms.total_delta,
                        "total_theta": ms.total_theta,
                        "instruments": [
                            {
                                "symbol": md.symbol,
                                "bid": md.bid,
                                "ask": md.ask,
                                "delta": md.delta,
                                "theta": md.theta,
                            }
                            for md in ms.market_datas
                        ],
                    }

                nodes.append(
                    {
                        "node_type": node.node_type,
                        "description": node.description,
                        "occurred_at": node.occurred_at,
                        "fill_cost": str(fill_cost),
                        "total_fees": str(node_fees),
                        "roll": node.roll or False,
                        "legs": legs,
                        "entries": entries,
                        "market_snapshot": snapshot,
                    }
                )

            # Open legs with current mark values
            open_legs = []
            unrealized = Decimal("0")
            for entry in cd.open_entries:
                sym = entry.symbol.strip()
                direction = "Short" if entry.quantity_type == "Short" else "Long"
                pos = pos_by_symbol.get(sym)
                mark_value: float | None = None
                if pos and pos["mid_price"] is not None:
                    mid = Decimal(str(pos["mid_price"]))
                    qty = Decimal(str(pos["quantity"]))
                    mult = Decimal(str(pos["multiplier"] or 1))
                    sign = (
                        Decimal("-1")
                        if str(pos["quantity_direction"]) == "Short"
                        or str(pos["quantity_direction"]) == "QuantityDirection.SHORT"
                        else Decimal("1")
                    )
                    mv = mid * qty * mult * sign
                    mark_value = float(mv)
                    unrealized += mv

                open_legs.append(
                    {
                        "symbol": sym,
                        "quantity": entry.quantity,
                        "direction": direction,
                        "mark_value": mark_value,
                    }
                )

            net_pnl = realized + unrealized
            results.append(
                {
                    "chain_id": chain.id,
                    "description": chain.description,
                    "underlying": chain.underlying_symbol,
                    "status": "open" if cd.open else "closed",
                    "rolls": cd.roll_count,
                    "realized_pnl": str(realized),
                    "total_fees": str(fees),
                    "unrealized_mark": str(unrealized),
                    "net_pnl": str(net_pnl),
                    "opened_at": cd.opened_at,
                    "nodes": nodes,
                    "open_legs": open_legs,
                }
            )

        return results

    # -- end TradeChain enrichment block --

    async def read(self) -> pd.DataFrame:
        """Read positions + market data + instruments from Redis, return joined DataFrame."""
        # 1. Read positions
        raw_positions = await self.redis.hgetall(AccountStreamPublisher.POSITIONS_KEY)
        if not raw_positions:
            return MetricsTracker().df

        # Correlate by symbol — REST hydration omits streamer_symbol,
        # live WebSocket events include it. Merge so every position has both.
        by_symbol: dict[str, Position] = {}
        for _key, value in raw_positions.items():
            try:
                pos = Position.model_validate(json.loads(value))
                existing = by_symbol.get(pos.symbol)
                if existing is None:
                    by_symbol[pos.symbol] = pos
                elif (
                    existing.streamer_symbol is None and pos.streamer_symbol is not None
                ):
                    by_symbol[pos.symbol] = pos
                elif (
                    pos.streamer_symbol is None and existing.streamer_symbol is not None
                ):
                    pass  # keep the one with streamer_symbol
            except Exception as e:
                logger.warning("Failed to parse position: %s", e)
        positions = list(by_symbol.values())

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

        # 5b. Fill instrument gaps from position symbols
        # After a roll, new option positions may exist before instruments are
        # re-fetched. Parse option_type, strike, and expiration from the symbol
        # so downstream consumers (DTE column, strategy classifier) have
        # complete data from a single source.
        option_re = re.compile(r"(\d{6})([CP])(.+)$")
        for pos in positions:
            if pos.symbol in self.instruments:
                continue
            if pos.instrument_type not in ("Future Option", "Equity Option"):
                continue
            parts = pos.symbol.strip().split()
            tail = parts[-1] if parts else pos.symbol
            m = option_re.search(tail)
            if not m:
                continue
            date_str, opt_char, strike_str = m.groups()
            try:
                exp_date = date(
                    2000 + int(date_str[:2]),
                    int(date_str[2:4]),
                    int(date_str[4:6]),
                )
                dte_val = (exp_date - date.today()).days
            except Exception:
                continue
            # OCC equity options encode strike * 1000 (8 digits)
            if pos.instrument_type == "Equity Option" and len(strike_str) == 8:
                try:
                    strike_val = str(int(strike_str) / 1000)
                except ValueError:
                    strike_val = strike_str
            else:
                strike_val = strike_str
            self.instruments[pos.symbol] = {
                "option-type": opt_char,
                "strike-price": strike_val,
                "expiration-date": exp_date.isoformat(),
                "days-to-expiration": dte_val,
            }
        # end 5b

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
        # Reads trade chain data from Redis, builds a symbol→chain lookup,
        # and enriches each position row with lifecycle data (rolls, P&L, fees).
        # Can be removed without side effects.
        raw_chains = await self.redis.hgetall(AccountStreamPublisher.TRADE_CHAINS_KEY)
        self.trade_chains = {}
        chain_by_symbol: dict[str, TradeChain] = {}
        for _key, value in raw_chains.items():
            try:
                chain = TradeChain.model_validate_json(value)
                self.trade_chains[chain.id] = chain
                if chain.computed_data.open:
                    for entry in chain.computed_data.open_entries:
                        chain_by_symbol[entry.symbol.strip()] = chain
            except Exception as e:
                logger.debug("Skipped trade chain: %s", e)

        if self.trade_chains:
            logger.info("Loaded %d trade chains from Redis", len(self.trade_chains))
        # -- end TradeChain enrichment block --

        # 8. Enrich DataFrame with entry credit data
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

        # 10. Compute dollar-denominated theta (theta * signed_qty * multiplier)
        # Raw theta from DXLink is always negative for options (decay erodes value).
        # Signed quantity flips the sign for short positions so dollar_theta is
        # positive when theta works in your favor (short) and negative when it
        # works against you (long). Matches Strategy.net_theta semantics.
        if not df.empty and "theta" in df.columns:
            sign = df["quantity_direction"].map(
                lambda d: -1.0 if d == QuantityDirection.SHORT else 1.0
            )
            df["dollar_theta"] = (
                df["theta"] * sign * df["quantity"] * df["multiplier"]
            ).round(2)

        # 11. Enrich positions with trade chain lifecycle data
        # -- TradeChain position enrichment (experimental) --
        # Maps each position to its parent trade chain via open-entry symbols.
        # Can be removed without side effects.
        if not df.empty and chain_by_symbol:
            lookup = chain_by_symbol

            def get_chain_id(sym: str) -> str | None:
                c = lookup.get(sym)
                return c.id if c else None

            def get_tt_strategy(sym: str) -> str | None:
                c = lookup.get(sym)
                return c.description if c else None

            def get_rolls(sym: str) -> int | None:
                c = lookup.get(sym)
                return c.computed_data.roll_count if c else None

            # TODO: P&L accounting needs work. realized_gain_with_fees is
            # misleading — it's realized_gain PLUS fees (not minus). For the
            # /6EM6 strangle: realized_gain=0.0, fees=7.68, with_fees=7.68.
            # Consider showing realized_gain (before fees) separately, or
            # computing net P&L = realized_gain - total_fees.
            def get_realized_pnl(sym: str) -> str | None:
                c = lookup.get(sym)
                return c.computed_data.realized_gain_with_fees if c else None

            def get_chain_fees(sym: str) -> str | None:
                c = lookup.get(sym)
                return c.computed_data.total_fees if c else None

            df["chain_id"] = df["symbol"].map(get_chain_id)
            df["tt_strategy"] = df["symbol"].map(get_tt_strategy)
            df["rolls"] = df["symbol"].map(get_rolls).astype("Int64")
            df["realized_pnl"] = df["symbol"].map(get_realized_pnl)
            df["chain_fees"] = df["symbol"].map(get_chain_fees)
        # -- end TradeChain position enrichment --

        # Round Greeks and IV to 2dp — least significant bits don't drive decisions
        for col in ("delta", "theta", "implied_volatility"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").round(2)

        self.position_metrics_df = df
        return self.position_metrics_df

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
