"""The chart's Kalman pane must carry the engine's warmup into the session."""

from datetime import datetime, timedelta, timezone

import polars as pl

from tastytrade.charting.indicators import KalmanState, StreamingIndicators


def session_frame(closes: list[float]) -> pl.DataFrame:
    t0 = datetime(2026, 9, 9, 13, 30, tzinfo=timezone.utc)
    return pl.DataFrame(
        {
            "time": [t0 + timedelta(minutes=5 * i) for i in range(len(closes))],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
        }
    )


class TestKalmanWarmup:
    def test_session_velocities_continue_the_warmup_run(self) -> None:
        warmup = [7673.5] * 40 + [7673.5 + 0.3 * i for i in range(20)]
        session = [7653.6, 7652.6, 7651.1, 7653.1, 7656.2, 7653.1, 7655.3]

        seeded = StreamingIndicators().seed(session_frame(session), 7673.5, warmup)
        pane = [p["velocity"] for p in seeded["kalman"]]

        continuous = KalmanState()
        for c in warmup:
            continuous.step(c)
        expected = []
        for c in session:
            continuous.step(c)
            expected.append(round(continuous.x_vel, 4))
        assert pane == expected

    def test_warmup_changes_the_opening_read(self) -> None:
        # a gap-down open after a flat prior session: warmed filter carries the
        # gap as negative velocity, a cold one reads the bounce as a turn
        session = [7653.6, 7652.6, 7651.1, 7653.1, 7656.2, 7653.1, 7655.3]
        cold = StreamingIndicators().seed(session_frame(session), 7673.5)
        warm = StreamingIndicators().seed(session_frame(session), 7673.5, [7673.5] * 60)
        assert cold["kalman"][4]["velocity"] > 0
        assert warm["kalman"][4]["velocity"] < 0

    def test_no_warmup_is_the_cold_start(self) -> None:
        session = [7650.0, 7651.0, 7652.0]
        a = StreamingIndicators().seed(session_frame(session), None)
        b = StreamingIndicators().seed(session_frame(session), None, [])
        assert a["kalman"] == b["kalman"]
