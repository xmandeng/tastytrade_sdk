"""Tests for the chart symbol dropdown freshness filter (TT-154).

`/api/symbols` populates the chart's symbol dropdown from the Redis
`subscriptions` hash. Orphaned entries (a producer that died without cleanup)
stay `active: True` but stop receiving events, so their `last_update` freezes.
`fresh_base_symbols` keeps the dropdown to candle feeds seen recently, without
touching the store or any recovery path.
"""

from datetime import datetime, timedelta, timezone

from tastytrade.charting.server import fresh_base_symbols

NOW = datetime(2026, 5, 26, 15, 0, 0, tzinfo=timezone.utc)
MAX_AGE = timedelta(days=4)


def sub(last_update: datetime | str | None) -> dict:
    """Build a subscription entry like RedisSubscriptionStore stores."""
    value = (
        last_update.isoformat() if isinstance(last_update, datetime) else last_update
    )
    return {"active": True, "last_update": value, "metadata": {}}


def test_fresh_candle_subscription_is_kept() -> None:
    subs = {"SPX{=5m}": sub(NOW - timedelta(hours=1))}
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == {"SPX"}


def test_stale_candle_subscription_is_dropped() -> None:
    # Orphan: last event was 5 days ago, beyond the 4-day window.
    subs = {"SPX{=5m}": sub(NOW - timedelta(days=5))}
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == set()


def test_boundary_just_inside_window_is_kept() -> None:
    subs = {"SPX{=5m}": sub(NOW - timedelta(days=4) + timedelta(minutes=1))}
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == {"SPX"}


def test_ticker_subscriptions_without_interval_are_ignored() -> None:
    # No `{=` suffix → not a candle feed → never in the dropdown (matches
    # the original endpoint behavior).
    subs = {"SPY": sub(NOW), "AAPL": sub(NOW)}
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == set()


def test_base_symbol_deduped_across_intervals() -> None:
    subs = {
        "SPX{=5m}": sub(NOW),
        "SPX{=1h}": sub(NOW - timedelta(hours=2)),
        "/ES{=5m}": sub(NOW),
    }
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == {"SPX", "/ES"}


def test_mixed_fresh_and_stale_keeps_only_fresh() -> None:
    subs = {
        "SPX{=5m}": sub(NOW - timedelta(hours=1)),  # fresh
        "QQQ{=5m}": sub(NOW - timedelta(days=10)),  # orphan
    }
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == {"SPX"}


def test_missing_last_update_is_excluded() -> None:
    # No authoritative timestamp → excluded, never assumed fresh.
    subs = {"SPX{=5m}": sub(None)}
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == set()


def test_unparseable_last_update_is_excluded() -> None:
    subs = {"SPX{=5m}": sub("not-a-timestamp")}
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == set()


def test_non_dict_entry_is_excluded() -> None:
    subs = {"SPX{=5m}": "corrupt"}  # type: ignore[dict-item]
    assert fresh_base_symbols(subs, now=NOW, max_age=MAX_AGE) == set()
