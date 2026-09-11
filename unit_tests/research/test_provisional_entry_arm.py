"""Provisional-entry arms: enter at the first intra-bar crossing of the
provisional velocity, manage a non-confirming bar out by scratch / clock /
-1x credit stop / long-strike breach, trade as production once the seal
confirms. Sealed arms never see these signals."""

from datetime import datetime, timedelta, timezone

from tastytrade.messaging.models.events import CandleEvent

from research.tt156_zero_dte_butterfly.config import VariantConfig
from research.tt156_zero_dte_butterfly.signals import SealedBarSignalEngine
from research.tt156_zero_dte_butterfly.simulator import (
    ButterflySimulator,
    Quotes,
    signal_matches,
)

SYM5 = "SPX{=5m}"
T0 = datetime(2026, 9, 11, 14, 30, tzinfo=timezone.utc)  # 10:30 ET bar


def bar(minute: int, close: float) -> CandleEvent:
    return CandleEvent(
        eventSymbol=SYM5, time=T0 + timedelta(minutes=minute), close=close
    )


def rising_engine() -> SealedBarSignalEngine:
    """Sealed regime Up: six rising closes, last sealed bar is T0-5."""
    eng = SealedBarSignalEngine(confirm_on_close=True)
    for i in range(6):
        eng.ingest_sealed(bar(-30 + 5 * i, 7580.0 + 2 * i), emit=False)
    eng.capture.drain()
    assert eng.kalman_sign == "Up"
    return eng


def test_first_crossing_emits_one_provisional_open_per_bar() -> None:
    eng = rising_engine()
    eng.provisional_signals(T0, 7592.0)  # in line with the regime
    assert eng.capture.drain() == []
    eng.provisional_signals(T0, 7560.0)  # crosses against it
    sigs = eng.capture.drain()
    assert [(s.signal_type, s.direction, s.trigger) for s in sigs] == [
        ("OPEN", "BEARISH", "kalman_provisional")
    ]
    assert sigs[0].engine == "kalman"
    eng.provisional_signals(T0, 7540.0)  # same bar: no second trigger
    assert eng.capture.drain() == []


def test_crossing_outside_the_window_is_silent() -> None:
    eng = rising_engine()
    early = T0.replace(hour=13, minute=30)  # 09:30 ET
    eng.provisional_signals(early, 7500.0)
    assert eng.capture.drain() == []


def test_already_sealed_bar_cannot_trigger() -> None:
    eng = rising_engine()
    eng.provisional_signals(T0 - timedelta(minutes=5), 7500.0)
    assert eng.capture.drain() == []


def test_non_confirming_seal_emits_false_start() -> None:
    eng = rising_engine()
    eng.provisional_signals(T0, 7560.0)
    eng.capture.drain()
    eng.ingest_sealed(bar(0, 7593.0), emit=True)  # closes with the regime
    sigs = eng.capture.drain()
    assert [(s.signal_type, s.direction, s.trigger) for s in sigs] == [
        ("FALSE_START", "BEARISH", "kalman_seal")
    ]
    assert eng.provisional_pending is None


def test_confirming_seal_emits_the_ordinary_flip_only() -> None:
    eng = rising_engine()
    eng.provisional_signals(T0, 7560.0)
    eng.capture.drain()
    eng.ingest_sealed(bar(0, 7550.0), emit=True)
    sigs = [
        (s.signal_type, s.direction, s.trigger)
        for s in eng.capture.drain()
        if s.engine == "kalman"
    ]
    assert sigs == [("CLOSE", "BULLISH", "kalman"), ("OPEN", "BEARISH", "kalman_flip")]
    assert eng.provisional_pending is None


# ---- simulator ----------------------------------------------------------

K = 7600.0
PROV = VariantConfig(
    name="w25_5m_m0_kal_prov",
    width=25.0,
    signal_interval="5m",
    completion_margin=0.0,
    signal_source="kalman",
    entry_timing="provisional",
)
SEALED = VariantConfig(
    name="w25_5m_m0_kal",
    width=25.0,
    signal_interval="5m",
    completion_margin=0.0,
    signal_source="kalman",
)


def quotes(short_put: float, long_put: float) -> Quotes:
    """Bull put vertical K/K-25 priced at short_put - long_put; calls far away."""
    q: Quotes = {}
    for strike, mid in ((K, short_put), (K - 25.0, long_put)):
        q[(strike, "P")] = {"bid": mid - 0.05, "ask": mid + 0.05, "mid": mid}
    for strike in (K, K + 25.0):
        q[(strike, "C")] = {"bid": 0.05, "ask": 0.15, "mid": 0.10}
    return q


def signal(kind: str, direction: str, trigger: str):
    eng = SealedBarSignalEngine()
    eng.emit_signal(
        CandleEvent(eventSymbol=SYM5, time=T0, close=K),
        kind,
        direction,
        trigger,
        0.0,
        engine="kalman",
    )
    return eng.capture.drain()[0]


PROV_OPEN = signal("OPEN", "BULLISH", "kalman_provisional")
FALSE_START = signal("FALSE_START", "BULLISH", "kalman_seal")
SEALED_OPEN = signal("OPEN", "BULLISH", "kalman_flip")


def test_routing_keeps_provisional_signals_off_sealed_arms() -> None:
    assert signal_matches(PROV, PROV_OPEN)
    assert signal_matches(PROV, FALSE_START)
    assert signal_matches(PROV, SEALED_OPEN)
    assert not signal_matches(SEALED, PROV_OPEN)
    assert not signal_matches(SEALED, FALSE_START)
    assert signal_matches(SEALED, SEALED_OPEN)


def opened() -> tuple[ButterflySimulator, list[dict]]:
    events: list[dict] = []
    sim = ButterflySimulator([PROV], event_sink=events.append)
    sim.on_snapshot(T0, K, quotes(9.0, 2.0), [PROV_OPEN])  # credit 7.0
    assert [e["event"] for e in events] == ["ENTRY"]
    assert sim.structures[0].entry_timing == "provisional"
    return sim, events


def test_exposed_vertical_leaves_at_the_first_scratch() -> None:
    sim, events = opened()
    t = T0 + timedelta(minutes=5)
    sim.on_snapshot(t, K, quotes(10.0, 2.0), [FALSE_START])  # -1.0, exposed
    assert sim.structures[0].exposed_at == t.isoformat()
    assert sim.structures[0].status == "OPEN"
    sim.on_snapshot(t + timedelta(minutes=3), K, quotes(8.9, 2.0), [])  # +0.1
    s = sim.structures[0]
    assert s.status == "CLOSED" and s.close_reason == "false_start_scratch"


def test_exposed_vertical_leaves_on_the_clock() -> None:
    sim, _ = opened()
    t = T0 + timedelta(minutes=5)
    sim.on_snapshot(t, K, quotes(10.0, 2.0), [FALSE_START])
    sim.on_snapshot(t + timedelta(minutes=29), K, quotes(10.0, 2.0), [])
    assert sim.structures[0].status == "OPEN"
    sim.on_snapshot(t + timedelta(minutes=30), K, quotes(10.0, 2.0), [])
    assert sim.structures[0].close_reason == "false_start_clock"


def test_unconfirmed_vertical_stops_at_one_credit_before_the_seal() -> None:
    sim, _ = opened()
    sim.on_snapshot(T0 + timedelta(minutes=2), K - 8, quotes(16.0, 2.0), [])  # -7.0
    assert sim.structures[0].close_reason == "false_start_stop"


def test_unconfirmed_vertical_leaves_on_a_long_strike_breach() -> None:
    sim, _ = opened()
    sim.on_snapshot(T0 + timedelta(minutes=2), K - 26, quotes(12.0, 2.0), [])  # -3.0
    assert sim.structures[0].close_reason == "false_start_breach"


def test_confirmed_vertical_is_never_stopped_and_not_re_entered() -> None:
    sim, events = opened()
    t = T0 + timedelta(minutes=5)
    sim.on_snapshot(t, K, quotes(9.0, 2.0), [SEALED_OPEN])
    assert [e["event"] for e in events] == ["ENTRY", "CONFIRMED"]
    assert len(sim.structures) == 1
    sim.on_snapshot(t + timedelta(minutes=2), K - 30, quotes(20.0, 3.0), [])  # -10.0
    assert sim.structures[0].status == "OPEN"


def test_sealed_flip_with_no_crossing_enters_the_provisional_arm() -> None:
    events: list[dict] = []
    sim = ButterflySimulator([PROV], event_sink=events.append)
    sim.on_snapshot(T0, K, quotes(9.0, 2.0), [SEALED_OPEN])
    assert sim.structures[0].entry_timing == "sealed"
    sim.on_snapshot(T0 + timedelta(minutes=2), K - 30, quotes(20.0, 3.0), [])
    assert sim.structures[0].status == "OPEN"


def test_family_flip_does_not_close_an_unconfirmed_vertical() -> None:
    sim, _ = opened()
    hull_close = signal("CLOSE", "BULLISH", "hull")
    sim.on_snapshot(T0 + timedelta(minutes=2), K, quotes(10.0, 2.0), [hull_close])
    assert sim.structures[0].status == "OPEN"
    sim.on_snapshot(T0 + timedelta(minutes=5), K, quotes(10.0, 2.0), [SEALED_OPEN])
    sim.on_snapshot(T0 + timedelta(minutes=7), K, quotes(10.0, 2.0), [hull_close])
    assert sim.structures[0].close_reason == "signal_hull"
