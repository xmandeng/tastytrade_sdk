"""Live signal generation for the research day.

Two engines live here:

- ``SealedBarSignalEngine`` — the ACTIVE forward-test engine: one pass
  over sealed 5m bars emits two signal families. The Kalman velocity
  flip (primary since 2026-08-28) drives entries on the kalman arms; the
  hull color flip (Basics v2, 2026-08-27) is the exit backstop on every
  arm and still drives the lagging-control hull arms. OPEN only inside
  the 10:00-13:00 ET window, CLOSE on the opposite flip of either
  family. MACD is nowhere (removed by user directive after the
  feed-lag contamination).
- ``LiveSignalEngine`` — the retired Hull/MACD confluence wrapper, kept
  for replay tooling and history.

Both warm up from InfluxDB and consume the live Redis candle channels
published by the already-running subscribe service.
"""

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import polars as pl

from tastytrade.analytics.engines.hull_macd import HullMacdEngine
from tastytrade.analytics.engines.models import TradeSignal
from tastytrade.analytics.indicators.momentum import hull, macd
from tastytrade.config import RedisConfigManager
from tastytrade.messaging.models.events import BaseEvent, CandleEvent
from tastytrade.messaging.processors.snapshot import REMOVE_EVENT
from tastytrade.providers.market import MarketDataProvider
from tastytrade.providers.subscriptions import RedisSubscription
from tastytrade.utils.time_series import initialize_influx_client

from research.tt156_zero_dte_butterfly.config import (
    ET as ET_TZ,
    HULL_ENTRY_END,
    HULL_ENTRY_START,
    KALMAN_Q_OVER_R,
    KALMAN_WARMUP_DAYS,
    PROVISIONAL_ENTRY_MAX_VELOCITY,
    SYMBOL,
)
from research.tt156_zero_dte_butterfly.gate import flip_eta

logger = logging.getLogger(__name__)

INTERVALS = ("m", "5m")
HULL_CANDLE_CAP = 500


def is_transaction_marker(event: CandleEvent) -> bool:
    """True for a dxFeed transaction record that must never act as a bar.

    dxFeed closes a candle transaction with a virtual REMOVE_EVENT record at
    index Long.MAX_VALUE: a 2038 timestamp, count 0, no prices. The bar-close
    gate below detects a new bar by a newer timestamp, so that record would
    seal the forming bar early on a partial close and the real close would
    then seal the same bar a second time. The check lives here, in the
    consumer that needs it: the publisher does not know what its readers
    need. A record with no close cannot be a bar for this engine either.
    """
    flags = event.eventFlags or 0
    return event.close is None or bool(flags & REMOVE_EVENT)


def as_utc(moment: datetime) -> datetime:
    """Warmup rows from InfluxDB arrive naive, live events aware; compare on one basis."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


class SignalCapture:
    """EventPublisher that collects TradeSignals for in-process consumption.

    The Redis listener fires callbacks from the event loop while the
    collector drains from its sampling loop — guard with a lock.
    """

    def __init__(self) -> None:
        self.captured: list[TradeSignal] = []
        self.lock = threading.Lock()

    def publish(self, event: BaseEvent) -> None:
        if isinstance(event, TradeSignal):
            with self.lock:
                self.captured.append(event)

    def drain(self) -> list[TradeSignal]:
        with self.lock:
            signals = self.captured[:]
            self.captured.clear()
        return signals


class LiveSignalEngine:
    """HullMacdEngine wrapper: InfluxDB warmup, live Redis feed, spot tracking."""

    def __init__(
        self, warmup_days: int = KALMAN_WARMUP_DAYS, confirm_on_close: bool = True
    ) -> None:
        self.capture = SignalCapture()
        self.engine = HullMacdEngine(publisher=self.capture)
        self.warmup_days = warmup_days
        self.confirm_on_close = confirm_on_close
        self.latest_spot: float | None = None
        self.latest_spot_time: datetime | None = None
        self.subscription: RedisSubscription | None = None
        # Per-symbol buffer of the still-forming candle, held until a newer
        # bar arrives (= the buffered bar has closed). Only sealed bars reach
        # the engine when confirm_on_close is set.
        self.forming: dict[str, CandleEvent] = {}

    def candle_symbols(self) -> list[str]:
        return [f"{SYMBOL}{{={interval}}}" for interval in INTERVALS]

    def gate_context(self) -> dict[str, float | None]:
        """Numeric MACD gate values from the engine's live sealed-bar windows.

        Computed on the exact ``state.candles`` frames the engine trades on
        (same ``macd()``, same prior-close seeding) so the recorded values
        are what the entry decision actually saw. Nothing else in the stack
        persists numeric MACD — this is the capture point.
        """
        ctx: dict[str, float | None] = {}
        for interval in INTERVALS:
            symbol = f"{SYMBOL}{{={interval}}}"
            suffix = "1m" if interval == "m" else interval
            hist: float | None = None
            slope: float | None = None
            state = self.engine._states.get(symbol)  # noqa: SLF001 — no public accessor
            prior = self.engine._prior_closes.get(symbol)  # noqa: SLF001
            if state is not None and state.candles.height >= 3:
                mdf = macd(state.candles, prior_close=prior)
                if mdf.height >= 2:
                    hist = float(mdf["diff"][-1])
                    slope = hist - float(mdf["diff"][-2])
            ctx[f"hist_{suffix}"] = hist
            ctx[f"slope_{suffix}"] = slope
            ctx[f"flip_eta_{suffix}"] = flip_eta(hist, slope)
        return ctx

    def warmup(self, session_date: date) -> None:
        """Replay recent history from InfluxDB through the engine."""
        influx = initialize_influx_client()
        provider = MarketDataProvider(
            data_feed=RedisSubscription(RedisConfigManager()), influx=influx
        )

        prior = provider.get_daily_candle(SYMBOL, session_date - timedelta(days=1))
        prior_close = float(prior.close) if prior.close is not None else None
        logger.info("Prior session close: %s", prior_close)

        for symbol in self.candle_symbols():
            if prior_close is not None:
                self.engine.set_prior_close(symbol, prior_close)
            df = provider.download(
                symbol=symbol,
                start=session_date - timedelta(days=self.warmup_days),
                stop=session_date,
            )
            if df.is_empty() or "time" not in df.columns:
                # No history in the warmup window (e.g. a Monday whose window
                # falls on the weekend, or an InfluxDB gap). Warmup is an
                # optimization, not a prerequisite — the engine warms up live
                # over the first candles. Never let an empty frame crash the
                # whole collection run.
                logger.warning(
                    "Warmup found no candles for %s in [%s, %s] — starting engine cold",
                    symbol,
                    session_date - timedelta(days=self.warmup_days),
                    session_date,
                )
                continue
            count = 0
            for row in df.sort("time").to_dicts():
                try:
                    self.engine.on_candle_event(CandleEvent(**row))
                    count += 1
                except Exception:
                    continue
            logger.info("Warmup replayed %d candles for %s", count, symbol)

        warmup_signals = len(self.capture.drain())
        logger.info("Discarded %d warmup signals", warmup_signals)
        # Warmup replay leaves yesterday's position flags set; today's book
        # starts flat, so reset the state machine but keep the candle history.
        for state in self.engine._states.values():  # noqa: SLF001 — no public accessor
            state.bullish_open = False
            state.bearish_open = False
            state.hull_armed_direction = None
            state.macd_armed_direction = None
        influx.close()

    async def start_live(self) -> None:
        """Subscribe to the live Redis candle channels."""
        self.subscription = RedisSubscription(RedisConfigManager())
        await self.subscription.connect()
        for symbol in self.candle_symbols():
            await self.subscription.subscribe(
                f"market:CandleEvent:{symbol}",
                event_type=CandleEvent,
                on_update=self.on_candle,
            )

    def on_candle(self, event: BaseEvent) -> None:
        if not isinstance(event, CandleEvent):
            return
        # Spot tracking stays live (drives chain centering) regardless of the
        # signal gate.
        if event.eventSymbol == f"{SYMBOL}{{=m}}" and event.close is not None:
            self.latest_spot = float(event.close)
            self.latest_spot_time = event.time

        if is_transaction_marker(event):
            return

        if not self.confirm_on_close:
            self.engine.on_candle_event(event)
            return

        # Bar-close gate: forward the previous bar to the engine only once a
        # newer bar opens (it has sealed); buffer the forming bar otherwise.
        # The engine never sees an intra-candle update, so a signal cannot fire
        # until its candle is complete.
        prev = self.forming.get(event.eventSymbol)
        if prev is not None and event.time > prev.time:
            self.engine.on_candle_event(prev)
        self.forming[event.eventSymbol] = event

    def state_summary(self) -> dict[str, dict[str, str | bool | None]]:
        summary: dict[str, dict[str, str | bool | None]] = {}
        for symbol, state in self.engine._states.items():  # noqa: SLF001
            summary[symbol] = {
                "hull_direction": state.hull_direction,
                "macd_position": state.macd_position,
                "hull_armed": state.hull_armed_direction,
                "macd_armed": state.macd_armed_direction,
                "bullish_open": state.bullish_open,
                "bearish_open": state.bearish_open,
            }
        return summary

    async def close(self) -> None:
        if self.subscription is not None:
            await self.subscription.close()


class SealedBarSignalEngine:
    """Sealed-bar 5m signal engine — two signal families from one pass.

    A constant-velocity Kalman filter (q/r=KALMAN_Q_OVER_R, 2026-08-28
    calibration) is the primary rule: a velocity sign flip on a sealed bar
    emits the ``engine="kalman"`` family that the simulator routes to
    ``signal_source="kalman"`` variants. The hull color flip emits the
    ``hull_only`` family: the exit backstop on every arm, and the entry
    rule for the lagging-control hull arms. Either family's flip emits
    CLOSE for the old direction (exits always fire); OPEN fires only
    inside the entry window. Interface-compatible with the collector's
    LiveSignalEngine usage. No MACD anywhere.
    """

    def __init__(
        self, warmup_days: int = KALMAN_WARMUP_DAYS, confirm_on_close: bool = True
    ) -> None:
        self.capture = SignalCapture()
        self.warmup_days = warmup_days
        self.confirm_on_close = confirm_on_close
        self.latest_spot: float | None = None
        self.latest_spot_time: datetime | None = None
        self.forming: dict[str, CandleEvent] = {}
        self.candles: pl.DataFrame = pl.DataFrame()
        self.prior_close: float | None = None
        self.hull_color: str | None = None
        self.subscription: RedisSubscription | None = None
        # Kalman state: [price, velocity per bar] and its 2x2 covariance,
        # recursive across warmup + live (exponential memory, no window).
        self.kalman_x: list[float] | None = None
        self.kalman_p: list[list[float]] = [[1.0, 0.0], [0.0, 1.0]]
        self.kalman_sign: str | None = None
        # The filter is recursive, so one bar must update it exactly once. The
        # hull rebuilds from a table deduped by bar time; the Kalman needs its
        # own guard against a bar that is presented twice (a warmup/live
        # overlap on restart, or a replay that repeats a bar).
        self.kalman_last_time: datetime | None = None
        # Provisional-entry tracking: the forming bar that already produced
        # its one crossing trigger, and the trigger awaiting its seal.
        self.provisional_bar: datetime | None = None
        self.provisional_pending: tuple[datetime, str] | None = None
        # collector reads len(signal_engine.engine.signals) for health counts
        self.engine = SimpleNamespace(signals=[])

    def candle_symbols(self) -> list[str]:
        return [f"{SYMBOL}{{={iv}}}" for iv in INTERVALS]

    def gate_context(self) -> dict[str, float | None] | None:
        """MACD gate retired — no context (simulator stamps None)."""
        return None

    def forming_bar_time(self) -> datetime | None:
        forming = self.forming.get(f"{SYMBOL}{{=5m}}")
        return forming.time if forming is not None else None

    def provisional_velocity(self, spot: float) -> float | None:
        """Velocity the filter would hold if the forming bar closed at ``spot``
        now: one predict+update on a copy of the sealed state. The sealed
        state itself is untouched; only the seal updates it."""
        if self.kalman_x is None:
            return None
        x, p = self.kalman_x, self.kalman_p
        r = 1.0
        q = KALMAN_Q_OVER_R * r
        xp = [x[0] + x[1], x[1]]
        p00 = p[0][0] + p[0][1] + p[1][0] + p[1][1] + q / 4
        p10 = p[1][0] + p[1][1] + q / 2
        k1 = p10 / (p00 + r)
        return xp[1] + k1 * (spot - xp[0])

    def provisional_signals(self, bar_time: datetime, spot: float) -> None:
        """Provisional-entry trigger: the first moment in a forming bar where
        the provisional velocity crosses against the sealed regime emits OPEN
        in the new direction (trigger ``kalman_provisional``), once per bar,
        only inside the entry window, and only when the sealed velocity
        entering the bar is already decayed (|v| at or below
        PROVISIONAL_ENTRY_MAX_VELOCITY). The seal then settles it in
        kalman_step: a confirming seal emits the ordinary flip, a
        non-confirming seal emits FALSE_START so the simulator manages the
        position out."""
        if self.kalman_sign is None or self.kalman_x is None:
            return
        if abs(self.kalman_x[1]) > PROVISIONAL_ENTRY_MAX_VELOCITY:
            return  # the regime is still fast; a crossing here is not an entry
        bar_time = as_utc(bar_time)
        if self.kalman_last_time is not None and bar_time <= self.kalman_last_time:
            return  # that bar has already sealed
        if self.provisional_bar == bar_time:
            return
        velocity = self.provisional_velocity(spot)
        if velocity is None:
            return
        sign = "Up" if velocity > 0 else "Down"
        if sign == self.kalman_sign:
            return
        self.provisional_bar = bar_time
        candle_et = bar_time.astimezone(ET_TZ).time()
        if not (HULL_ENTRY_START <= candle_et <= HULL_ENTRY_END):
            return
        self.provisional_pending = (bar_time, sign)
        self.emit_signal(
            CandleEvent(eventSymbol=f"{SYMBOL}{{=5m}}", time=bar_time, close=spot),
            "OPEN",
            "BULLISH" if sign == "Up" else "BEARISH",
            "kalman_provisional",
            velocity,
            engine="kalman",
        )

    def warmup(self, session_date: date) -> None:
        """Replay recent 5m history from InfluxDB; discard warmup signals."""
        influx = initialize_influx_client()
        provider = MarketDataProvider(
            data_feed=RedisSubscription(RedisConfigManager()), influx=influx
        )
        prior = provider.get_daily_candle(SYMBOL, session_date - timedelta(days=1))
        self.prior_close = float(prior.close) if prior.close is not None else None
        logger.info("Prior session close: %s", self.prior_close)
        df = provider.download(
            symbol=f"{SYMBOL}{{=5m}}",
            start=session_date - timedelta(days=self.warmup_days),
            stop=session_date,
        )
        count = 0
        if not df.is_empty() and "time" in df.columns and "close" in df.columns:
            for row in df.sort("time").to_dicts():
                try:
                    self.ingest_sealed(CandleEvent(**row), emit=False)
                    count += 1
                except Exception:
                    continue
        else:
            logger.warning("Warmup found no 5m candles — starting hull engine cold")
        logger.info("Warmup replayed %d candles for %s{=5m}", count, SYMBOL)
        influx.close()

    async def start_live(self) -> None:
        self.subscription = RedisSubscription(RedisConfigManager())
        await self.subscription.connect()
        for symbol in self.candle_symbols():
            await self.subscription.subscribe(
                f"market:CandleEvent:{symbol}",
                event_type=CandleEvent,
                on_update=self.on_candle,
            )

    def on_candle(self, event: BaseEvent) -> None:
        if not isinstance(event, CandleEvent):
            return
        if event.eventSymbol == f"{SYMBOL}{{=m}}" and event.close is not None:
            self.latest_spot = float(event.close)
            self.latest_spot_time = event.time
        if event.eventSymbol != f"{SYMBOL}{{=5m}}":
            return
        if is_transaction_marker(event):
            return
        if not self.confirm_on_close:
            self.ingest_sealed(event, emit=True)
            return
        prev = self.forming.get(event.eventSymbol)
        if prev is not None and event.time > prev.time:
            self.ingest_sealed(prev, emit=True)
        self.forming[event.eventSymbol] = event

    def ingest_sealed(self, event: CandleEvent, emit: bool) -> None:
        if event.close is None:
            return
        self.kalman_step(event, emit)
        row = pl.DataFrame([event])
        if self.candles.height == 0:
            self.candles = row
        else:
            self.candles = (
                self.candles.vstack(row)
                .unique(subset=["eventSymbol", "time"], keep="last")
                .sort("time", descending=False)
            )
        if self.candles.height > HULL_CANDLE_CAP:
            self.candles = self.candles.tail(HULL_CANDLE_CAP)
        if self.candles.height < 2:
            return
        hull_df = hull(self.candles, pad_value=self.prior_close)
        if hull_df.height == 0:
            return
        color = str(hull_df["HMA_color"][-1])
        prev_color = self.hull_color
        self.hull_color = color
        if not emit or prev_color is None or color == prev_color:
            return
        candle_et = event.time.astimezone(ET_TZ).time()
        new_dir = "BULLISH" if color == "Up" else "BEARISH"
        old_dir = "BEARISH" if new_dir == "BULLISH" else "BULLISH"
        hull_value = float(hull_df["HMA"][-1])
        self.emit_signal(event, "CLOSE", old_dir, "hull", hull_value)
        if HULL_ENTRY_START <= candle_et <= HULL_ENTRY_END:
            self.emit_signal(event, "OPEN", new_dir, "hull_flip", hull_value)

    def kalman_step(self, event: CandleEvent, emit: bool) -> None:
        """Constant-velocity Kalman update on one sealed close; emit the
        ``engine="kalman"`` signal family on a velocity sign flip."""
        bar_time = as_utc(event.time)
        if self.kalman_last_time is not None and bar_time <= self.kalman_last_time:
            return
        self.kalman_last_time = bar_time
        z = float(event.close or 0.0)
        if self.kalman_x is None:
            self.kalman_x = [z, 0.0]
        r = 1.0
        q = KALMAN_Q_OVER_R * r
        x, p = self.kalman_x, self.kalman_p
        # predict
        x = [x[0] + x[1], x[1]]
        p00 = p[0][0] + p[0][1] + p[1][0] + p[1][1] + q / 4
        p01 = p[0][1] + p[1][1] + q / 2
        p10 = p[1][0] + p[1][1] + q / 2
        p11 = p[1][1] + q
        # update
        s = p00 + r
        k0, k1 = p00 / s, p10 / s
        y = z - x[0]
        self.kalman_x = [x[0] + k0 * y, x[1] + k1 * y]
        self.kalman_p = [
            [(1 - k0) * p00, (1 - k0) * p01],
            [p10 - k1 * p00, p11 - k1 * p01],
        ]
        sign = "Up" if self.kalman_x[1] > 0 else "Down"
        prev_sign = self.kalman_sign
        self.kalman_sign = sign
        pending = self.provisional_pending
        if pending is not None and as_utc(event.time) >= pending[0]:
            self.provisional_pending = None
            if emit and sign != pending[1]:
                self.emit_signal(
                    event,
                    "FALSE_START",
                    "BULLISH" if pending[1] == "Up" else "BEARISH",
                    "kalman_seal",
                    self.kalman_x[1],
                    engine="kalman",
                )
        if not emit or prev_sign is None or sign == prev_sign:
            return
        candle_et = event.time.astimezone(ET_TZ).time()
        new_dir = "BULLISH" if sign == "Up" else "BEARISH"
        old_dir = "BEARISH" if new_dir == "BULLISH" else "BULLISH"
        velocity = self.kalman_x[1]
        self.emit_signal(event, "CLOSE", old_dir, "kalman", velocity, engine="kalman")
        if HULL_ENTRY_START <= candle_et <= HULL_ENTRY_END:
            self.emit_signal(
                event, "OPEN", new_dir, "kalman_flip", velocity, engine="kalman"
            )

    def emit_signal(
        self,
        event: CandleEvent,
        signal_type: str,
        direction: str,
        trigger: str,
        hull_value: float,
        engine: str = "hull_only",
    ) -> None:
        signal = TradeSignal(
            eventSymbol=event.eventSymbol,
            start_time=event.time,
            label=f"{signal_type} {direction}",
            color="#55A868" if direction == "BULLISH" else "#8C8C8C",
            line_width=0.5,
            line_dash="dot",
            opacity=0.4,
            signal_type=signal_type,
            direction=direction,
            engine=engine,
            hull_direction=self.hull_color or "Unknown",
            hull_value=hull_value,
            macd_value=0.0,
            macd_signal=0.0,
            macd_histogram=0.0,
            close_price=float(event.close or 0.0),
            trigger=trigger,
        )
        logger.info(
            "TradeSignal: %s %s %s at %s (trigger=%s)",
            signal_type,
            direction,
            event.eventSymbol,
            event.time,
            trigger,
        )
        self.engine.signals.append(signal)
        self.capture.publish(signal)

    def state_summary(self) -> dict[str, dict[str, str | bool | None]]:
        return {
            f"{SYMBOL}{{=5m}}": {
                "hull_direction": self.hull_color,
                "kalman_direction": self.kalman_sign,
                "macd_position": None,
                "hull_armed": None,
                "macd_armed": None,
                "bullish_open": False,
                "bearish_open": False,
            }
        }

    async def close(self) -> None:
        if self.subscription is not None:
            await self.subscription.close()
