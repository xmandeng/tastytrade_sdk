"""Query and format subscription status from Redis.

Connects to the Redis subscription store and returns structured status
information for display by the CLI status command.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as aioredis  # type: ignore


@dataclass
class SubscriptionInfo:
    """Parsed subscription entry from Redis."""

    symbol: str
    active: bool
    last_update: datetime | None
    metadata: dict = field(default_factory=dict)

    @property
    def feed_type(self) -> str:
        """Classify subscription by symbol format."""
        if "{=" in self.symbol:
            return "Candle"
        return "Ticker"

    @property
    def age_seconds(self) -> float | None:
        """Seconds since last update, or None if unknown."""
        if self.last_update is None:
            return None
        delta = datetime.now(timezone.utc) - self.last_update
        return delta.total_seconds()

    @property
    def age_display(self) -> str:
        """Human-readable age string."""
        age = self.age_seconds
        if age is None:
            return "unknown"
        if age < 60:
            return f"{age:.0f}s ago"
        if age < 3600:
            return f"{age / 60:.0f}m ago"
        if age < 86400:
            return f"{age / 3600:.1f}h ago"
        return f"{age / 86400:.1f}d ago"


@dataclass
class StatusResult:
    """Aggregated status information."""

    redis_connected: bool = False
    redis_version: str = ""
    subscriptions: list[SubscriptionInfo] = field(default_factory=list)
    error: str | None = None

    @property
    def active_subscriptions(self) -> list[SubscriptionInfo]:
        return [s for s in self.subscriptions if s.active]

    @property
    def candle_subscriptions(self) -> list[SubscriptionInfo]:
        return [s for s in self.active_subscriptions if s.feed_type == "Candle"]

    @property
    def ticker_subscriptions(self) -> list[SubscriptionInfo]:
        return [s for s in self.active_subscriptions if s.feed_type == "Ticker"]


def _parse_subscription(symbol: str, raw: dict) -> SubscriptionInfo:
    """Parse a raw Redis subscription entry."""
    last_update = None
    if ts := raw.get("last_update"):
        try:
            last_update = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            pass

    return SubscriptionInfo(
        symbol=symbol,
        active=raw.get("active", False),
        last_update=last_update,
        metadata=raw.get("metadata", {}),
    )


async def query_status(
    host: str | None = None,
    port: int | None = None,
    hash_key: str = "subscriptions",
) -> StatusResult:
    """Query Redis for current subscription status.

    Args:
        host: Redis host (defaults to REDIS_HOST env var or "redis").
        port: Redis port (defaults to REDIS_PORT env var or 6379).
        hash_key: Redis hash key for subscriptions.

    Returns:
        StatusResult with connection info and subscription data.
    """
    result = StatusResult()
    redis_host = host or os.environ.get("REDIS_HOST", "redis")
    redis_port = port or int(os.environ.get("REDIS_PORT", "6379"))

    client = aioredis.Redis(host=str(redis_host), port=int(redis_port), db=0)
    try:
        # Check connectivity
        await asyncio.wait_for(client.ping(), timeout=5.0)
        result.redis_connected = True

        info = await client.info("server")
        result.redis_version = info.get("redis_version", "unknown")

        # Fetch all subscriptions
        all_subs = await client.hgetall(hash_key)
        for key_bytes, val_bytes in all_subs.items():
            symbol = key_bytes.decode("utf-8")
            raw = json.loads(val_bytes.decode("utf-8"))
            result.subscriptions.append(_parse_subscription(symbol, raw))

        # Sort: active first, then by symbol
        result.subscriptions.sort(key=lambda s: (not s.active, s.feed_type, s.symbol))

    except (ConnectionError, OSError, asyncio.TimeoutError) as e:
        result.error = f"Cannot connect to Redis at {redis_host}:{redis_port} — {e}"
    finally:
        await client.close()  # type: ignore[union-attr]

    return result


def format_status(result: StatusResult, as_json: bool = False) -> str:
    """Format StatusResult for terminal display.

    Args:
        result: The query result to format.
        as_json: If True, return JSON output instead of table.

    Returns:
        Formatted string for terminal output.
    """
    if as_json:
        return _format_json(result)
    return _format_table(result)


def _format_json(result: StatusResult) -> str:
    """Format as JSON for machine consumption."""
    data: dict[str, object] = {
        "redis": {
            "connected": result.redis_connected,
            "version": result.redis_version,
        },
        "subscriptions": {
            "active": len(result.active_subscriptions),
            "total": len(result.subscriptions),
            "candle": [
                {
                    "symbol": s.symbol,
                    "last_update": s.last_update.isoformat() if s.last_update else None,
                    "age": s.age_display,
                }
                for s in result.candle_subscriptions
            ],
            "ticker": [
                {
                    "symbol": s.symbol,
                    "last_update": s.last_update.isoformat() if s.last_update else None,
                    "age": s.age_display,
                }
                for s in result.ticker_subscriptions
            ],
        },
    }
    if result.error:
        data["error"] = result.error
    return json.dumps(data, indent=2)


def _format_table(result: StatusResult) -> str:
    """Format as a readable terminal table."""
    lines: list[str] = []

    # Connection health
    lines.append("Connection Health")
    lines.append("-" * 40)
    redis_status = "Connected" if result.redis_connected else "Disconnected"
    if result.redis_connected:
        redis_status += f" (v{result.redis_version})"
    lines.append(f"  Redis:    {redis_status}")

    if result.error:
        lines.append(f"  Error:    {result.error}")
        return "\n".join(lines)

    active = result.active_subscriptions
    if not active:
        lines.append("")
        lines.append("No active subscriptions")
        return "\n".join(lines)

    # Summary counts
    lines.append("")
    lines.append(f"Active Subscriptions: {len(active)}")
    lines.append("-" * 40)

    # Ticker feeds
    tickers = result.ticker_subscriptions
    if tickers:
        lines.append(f"  Ticker feeds: {len(tickers)}")
        for sub in tickers:
            lines.append(f"    {sub.symbol:<20s} {sub.age_display}")

    # Candle feeds
    candles = result.candle_subscriptions
    if candles:
        lines.append(f"  Candle feeds: {len(candles)}")
        for sub in candles:
            lines.append(f"    {sub.symbol:<20s} {sub.age_display}")

    return "\n".join(lines)
