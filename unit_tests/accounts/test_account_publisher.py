"""Tests for AccountStreamPublisher — bridges AccountStreamer queues to Redis."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tastytrade.accounts.models import AccountBalance, Position
from tastytrade.accounts.publisher import AccountStreamPublisher


def make_position_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "symbol": "SPY",
        "instrument-type": "Equity",
        "quantity": "100.0",
        "quantity-direction": "Long",
        "streamer-symbol": "SPY",
    }
    base.update(overrides)
    return base


def make_balance_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account-number": "5WT00001",
        "cash-balance": "25000.50",
        "net-liquidating-value": "50000.75",
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def publisher(mock_redis: AsyncMock) -> AccountStreamPublisher:
    pub = AccountStreamPublisher.__new__(AccountStreamPublisher)
    pub.redis = mock_redis
    return pub


def test_position_redis_key() -> None:
    assert AccountStreamPublisher.POSITIONS_KEY == "tastytrade:positions"


def test_balance_redis_key() -> None:
    assert AccountStreamPublisher.BALANCES_KEY == "tastytrade:balances"


@pytest.mark.asyncio
async def test_publish_position_writes_hset(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    position = Position.model_validate(make_position_data())
    await publisher.publish_position(position)
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "tastytrade:positions"
    assert call_args[0][1] == "SPY"  # keyed by streamer_symbol


@pytest.mark.asyncio
async def test_publish_position_uses_symbol_when_no_streamer(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    position = Position.model_validate(
        make_position_data(**{"streamer-symbol": None})
    )
    await publisher.publish_position(position)
    call_args = mock_redis.hset.call_args
    assert call_args[0][1] == "SPY"  # falls back to symbol


@pytest.mark.asyncio
async def test_publish_position_removes_zero_quantity(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    position = Position.model_validate(
        make_position_data(quantity="0.0", **{"quantity-direction": "Zero"})
    )
    await publisher.publish_position(position)
    mock_redis.hdel.assert_called_once_with("tastytrade:positions", "SPY")


@pytest.mark.asyncio
async def test_publish_balance_writes_hset(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    balance = AccountBalance.model_validate(make_balance_data())
    await publisher.publish_balance(balance)
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "tastytrade:balances"
    assert call_args[0][1] == "5WT00001"


@pytest.mark.asyncio
async def test_publish_position_also_publishes_pubsub(
    publisher: AccountStreamPublisher, mock_redis: AsyncMock
) -> None:
    position = Position.model_validate(make_position_data())
    await publisher.publish_position(position)
    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[1]["channel"]
    assert channel == "tastytrade:events:CurrentPosition"
