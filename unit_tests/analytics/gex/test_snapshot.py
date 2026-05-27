"""Unit tests for the GEX snapshot orchestrator, cache, and client helpers (TT-139).

Async paths are driven via ``asyncio.run`` so these tests need no asyncio plugin.
"""

import asyncio

import pytest

from tastytrade.analytics.gex.client import parse_float, resolve_symbol_context
from tastytrade.analytics.gex.snapshot import (
    SnapshotEnvelope,
    snapshot_key,
    take_snapshot,
)


class FakeRedis:
    """Minimal async stand-in for redis.asyncio.Redis (get/set with TTL capture)."""

    def __init__(self, store=None):
        self.store = dict(store or {})
        self.sets: list[tuple] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.sets.append((key, value, ex))
        self.store[key] = value


def make_envelope(symbol="SPX", expirations=("2026-05-19",)):
    return SnapshotEnvelope(
        symbol=symbol,
        spot=7000.0,
        multiplier=100.0,
        expirations=sorted(expirations),
        computed_at="2026-05-19T13:35:00+00:00",
        strikes=[{"expiration": "2026-05-19", "strike": 7000.0, "net_gex": 1.0}],
        levels=[{"expiration": "2026-05-19", "call_wall": 7050.0}],
    )


def test_snapshot_key_is_sorted_and_joined():
    assert snapshot_key("SPX", ["2026-05-20", "2026-05-19"]) == (
        "gex:snapshot:SPX:2026-05-19,2026-05-20"
    )


def test_envelope_json_round_trip():
    env = make_envelope()
    assert SnapshotEnvelope.from_json(env.to_json()) == env


def test_cache_hit_returns_cached_without_session():
    env = make_envelope()
    key = snapshot_key(env.symbol, env.expirations)
    fake = FakeRedis({key: env.to_json()})

    # No session is passed; a cache hit must avoid any network/session work.
    out = asyncio.run(
        take_snapshot(env.symbol, env.expirations, redis=fake, use_cache=True)
    )
    assert out == env
    assert fake.sets == []  # nothing re-written on a hit


def test_parse_float_handles_strings_and_invalid():
    assert parse_float("1.5") == 1.5
    assert parse_float(2) == 2.0
    assert parse_float(None) is None
    assert parse_float("not-a-number") is None


def test_resolve_symbol_context_rejects_futures():
    with pytest.raises(NotImplementedError):
        asyncio.run(resolve_symbol_context(object(), "/ES"))
