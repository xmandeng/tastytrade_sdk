"""Day collector — samples the 0DTE chain, records snapshots, drives the simulator.

Bounded by the session clock: starts sampling at 09:28 ET and exits after
16:15 ET (or after ``max_cycles`` in test mode).
"""

import asyncio
import gzip
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta

import polars as pl

from tastytrade.config import RedisConfigManager
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler

from research.tt156_zero_dte_butterfly.chain import (
    fetch_index_summary,
    fetch_market_data,
    fetch_spot_rest,
    resolve_chain,
)
from research.tt156_zero_dte_butterfly.config import (
    ET,
    MARKET_CLOSE,
    SESSION_END,
    SESSION_START,
    SYMBOL,
    RunConfig,
)
from research.tt156_zero_dte_butterfly import regime
from research.tt156_zero_dte_butterfly.signals import HullSignalEngine
from research.tt156_zero_dte_butterfly.pinfly import (
    PinFlySimulator,
    default_pinfly_arms,
)
from research.tt156_zero_dte_butterfly.simulator import (
    ButterflySimulator,
    JsonlEventSink,
    Quotes,
)

logger = logging.getLogger(__name__)


class DayCollector:
    def __init__(self, run_config: RunConfig) -> None:
        self.cfg = run_config
        self.session: AsyncSessionHandler | None = None
        self.signal_engine = HullSignalEngine(
            warmup_days=run_config.warmup_days,
            confirm_on_close=run_config.confirm_on_close,
        )
        event_sink = JsonlEventSink(str(run_config.data_dir / "events.jsonl"))
        self.simulator = ButterflySimulator(
            run_config.variants,
            event_sink=event_sink,
        )
        self.pinfly = PinFlySimulator(
            default_pinfly_arms(),
            tent_exists=self.kal_tent_exists,
            event_sink=event_sink,
        )
        self.chain_df: pl.DataFrame | None = None
        self.occ_to_meta: dict[str, tuple[float, str]] = {}
        self.window_lo: float = 0.0
        self.window_hi: float = 0.0
        self.expiration: str = ""
        self.cycles: int = 0
        self.settlement_spot: float | None = None
        self.last_snapshot_ts: datetime | None = None
        self.day_atr: float | None = None
        self.spot_path: list[tuple[int, float]] = []

    def kal_tent_exists(self) -> bool:
        """Any kalman-family fly completed so far today (the pin-fly
        no-tent trigger asks: has the primary already secured its payoff)."""
        return any(
            s.variant.endswith(("_kal", "_kal_ef5"))
            and s.status in ("COMPLETED", "SETTLED")
            for s in self.simulator.structures
        )

    def now_et(self) -> datetime:
        return datetime.now(tz=ET)

    async def spot(self) -> float:
        live = self.signal_engine.latest_spot
        live_ts = self.signal_engine.latest_spot_time
        if (
            live is not None
            and live_ts is not None
            and self.now_et() - live_ts.astimezone(ET) < timedelta(minutes=3)
        ):
            return live
        assert self.session is not None
        return await fetch_spot_rest(self.session)

    async def load_chain(self, spot: float) -> None:
        assert self.session is not None
        df = await resolve_chain(
            self.session, self.expiration, spot, self.cfg.strike_window
        )
        if df.is_empty():
            raise RuntimeError(f"No {SYMBOL} options for expiration {self.expiration}")
        self.chain_df = df
        self.occ_to_meta = {
            row["symbol"]: (float(row["strike"]), str(row["option_type"]))
            for row in df.to_dicts()
        }
        strikes = df["strike"]
        self.window_lo, self.window_hi = float(strikes.min()), float(strikes.max())  # type: ignore[arg-type]
        logger.info(
            "Chain loaded: %d contracts, strikes %.0f-%.0f",
            len(self.occ_to_meta),
            self.window_lo,
            self.window_hi,
        )

    async def maybe_recenter(self, spot: float) -> None:
        if (
            spot - self.window_lo > self.cfg.recenter_buffer
            and self.window_hi - spot > self.cfg.recenter_buffer
        ):
            return
        logger.info("Spot %.2f near window edge — re-resolving chain", spot)
        previous = dict(self.occ_to_meta)
        await self.load_chain(spot)
        # Keep prior symbols so open structures stay priceable after drift.
        for occ, meta in previous.items():
            self.occ_to_meta.setdefault(occ, meta)

    async def write_header(self, spot: float) -> None:
        assert self.session is not None
        header: dict = {
            "date": self.now_et().date().isoformat(),
            "expiration": self.expiration,
            "spot_at_start": spot,
            "strike_window": [self.window_lo, self.window_hi],
            "cadence_seconds": self.cfg.cadence_seconds,
            "variants": [asdict(v) for v in self.cfg.variants],
            "index_summary": await fetch_index_summary(self.session),
        }
        try:
            from tastytrade.analytics.gex.snapshot import take_snapshot

            envelope = await take_snapshot(
                SYMBOL, [self.expiration], session=self.session
            )
            header["gex"] = json.loads(json.dumps(asdict(envelope), default=str))
        except Exception as exc:
            logger.warning("GEX snapshot unavailable: %s", exc)
            header["gex"] = None
        path = self.cfg.data_dir / "header.json"
        path.write_text(json.dumps(header, indent=2, default=str))
        logger.info("Header written to %s", path)

    def write_snapshot(self, ts: datetime, spot: float, market: dict) -> None:
        record = {
            "ts": ts.isoformat(),
            "spot": spot,
            "engine": self.signal_engine.state_summary(),
            "options": [
                {
                    "strike": self.occ_to_meta[occ][0],
                    "cp": self.occ_to_meta[occ][1],
                    **fields,
                }
                for occ, fields in market.items()
                if occ in self.occ_to_meta
            ],
        }
        path = self.cfg.data_dir / "chain_snapshots.jsonl.gz"
        with gzip.open(path, "at", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    def write_health(self, ts: datetime, spot: float, quote_count: int) -> None:
        summary = self.simulator.summary()
        health = {
            "ts": ts.isoformat(),
            "cycles": self.cycles,
            "spot": spot,
            "quotes_in_last_snapshot": quote_count,
            "signals_seen": len(self.signal_engine.engine.signals),
            "structures": len(self.simulator.structures),
            "total_pnl_points": summary["total_pnl_points"],
            "engine": self.signal_engine.state_summary(),
        }
        (self.cfg.data_dir / "health.json").write_text(
            json.dumps(health, indent=2, default=str)
        )

    def build_quotes(self, market: dict) -> Quotes:
        return {
            self.occ_to_meta[occ]: fields
            for occ, fields in market.items()
            if occ in self.occ_to_meta
        }

    def session_finished(self, now: datetime) -> bool:
        if self.cfg.max_cycles is not None and self.cycles >= self.cfg.max_cycles:
            return True
        if self.cfg.ignore_session_times:
            return False
        return now.time() >= SESSION_END

    async def wait_for_session_start(self) -> None:
        if self.cfg.ignore_session_times:
            return
        while self.now_et().time() < SESSION_START:
            remaining = (
                datetime.combine(self.now_et().date(), SESSION_START, tzinfo=ET)
                - self.now_et()
            )
            logger.info("Waiting %.0fs for session start", remaining.total_seconds())
            await asyncio.sleep(min(60.0, max(1.0, remaining.total_seconds())))

    async def run(self) -> dict:
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.expiration = self.now_et().date().isoformat()

        self.session = await AsyncSessionHandler.create(
            Credentials(RedisConfigManager(), env="Live")
        )
        self.signal_engine.warmup(self.now_et().date())
        await self.signal_engine.start_live()

        await self.wait_for_session_start()

        spot = await self.spot()
        await self.load_chain(spot)
        await self.write_header(spot)
        self.day_atr = regime.trailing_atr(self.cfg.data_dir)

        while not self.session_finished(self.now_et()):
            cycle_start = self.now_et()
            try:
                # OAuth access tokens live 900s — refresh before each cycle.
                # Both awaits are bounded: an unresponsive HTTP call must fail
                # the cycle (logged, retried next cycle), not hang the loop.
                await asyncio.wait_for(
                    self.session.refresh_token_if_needed(), timeout=30
                )
                market = await asyncio.wait_for(
                    fetch_market_data(self.session, list(self.occ_to_meta.keys())),
                    timeout=45,
                )
                spot = await asyncio.wait_for(self.spot(), timeout=30)
                quotes = self.build_quotes(market)
                signals = self.signal_engine.capture.drain()
                self.write_snapshot(cycle_start, spot, market)
                gate_ctx = self.signal_engine.gate_context() if signals else None
                self.spot_path.append(
                    (cycle_start.hour * 60 + cycle_start.minute, spot)
                )
                regime_state = regime.rolling_state(self.spot_path, self.day_atr)
                self.simulator.on_snapshot(
                    cycle_start, spot, quotes, signals, gate_ctx, regime_state
                )
                self.pinfly.on_snapshot(cycle_start, spot, quotes)
                if cycle_start.time() <= MARKET_CLOSE:
                    self.settlement_spot = spot
                self.cycles += 1
                self.write_health(cycle_start, spot, len(quotes))
                await self.maybe_recenter(spot)
            except Exception:
                logger.exception("Cycle failed — continuing")
            elapsed = (self.now_et() - cycle_start).total_seconds()
            await asyncio.sleep(max(0.5, self.cfg.cadence_seconds - elapsed))

        settle_spot = self.settlement_spot if self.settlement_spot is not None else spot
        self.simulator.settle(self.now_et(), settle_spot)
        self.pinfly.settle(self.now_et(), settle_spot)
        results = self.simulator.summary()
        results["settlement_spot"] = settle_spot
        results["cycles"] = self.cycles
        (self.cfg.data_dir / "final_results.json").write_text(
            json.dumps(results, indent=2, default=str)
        )
        logger.info("Day complete: %d cycles, results written", self.cycles)

        await self.signal_engine.close()
        await self.session.session.close()
        return results
