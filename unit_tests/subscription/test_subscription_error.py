"""Tests for SubscriptionError and retry reset logic."""

from tastytrade.subscription.orchestrator import SubscriptionError


def test_subscription_error_default_not_healthy() -> None:
    err = SubscriptionError("connection lost")
    assert str(err) == "connection lost"
    assert err.was_healthy is False


def test_subscription_error_healthy_flag() -> None:
    err = SubscriptionError("auth expired", was_healthy=True)
    assert err.was_healthy is True
    assert "auth expired" in str(err)


def test_subscription_error_is_exception() -> None:
    err = SubscriptionError("test")
    assert isinstance(err, Exception)
