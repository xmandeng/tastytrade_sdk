"""Tests for account stream orchestrator — self-healing lifecycle."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.accounts.orchestrator import (
    AccountStreamError,
    account_failure_trigger_listener,
    consume_balances,
    consume_positions,
    run_account_stream,
    run_account_stream_once,
    update_account_connection_status,
)
from tastytrade.accounts.models import AccountBalance, Position
from tastytrade.config.enumerations import AccountEventType, ReconnectReason


# ---------------------------------------------------------------------------
# AccountStreamError
# ---------------------------------------------------------------------------


class TestAccountStreamError:
    def test_was_healthy_true(self) -> None:
        err = AccountStreamError("test", was_healthy=True)
        assert err.was_healthy is True
        assert str(err) == "test"

    def test_was_healthy_false(self) -> None:
        err = AccountStreamError("test", was_healthy=False)
        assert err.was_healthy is False

    def test_was_healthy_default(self) -> None:
        err = AccountStreamError("test")
        assert err.was_healthy is False

    def test_is_exception(self) -> None:
        assert issubclass(AccountStreamError, Exception)


# ---------------------------------------------------------------------------
# update_account_connection_status
# ---------------------------------------------------------------------------


class TestUpdateAccountConnectionStatus:
    @pytest.mark.asyncio
    async def test_publishes_connected_status(self) -> None:
        """Connected state is written to Redis with timestamp."""
        mock_redis = AsyncMock()
        await update_account_connection_status(mock_redis, state="connected")
        mock_redis.hset.assert_awaited_once()
        call_kwargs = mock_redis.hset.call_args
        assert call_kwargs[0][0] == "tastytrade:account_connection"
        mapping = call_kwargs[1]["mapping"]
        assert mapping["state"] == "connected"
        assert "timestamp" in mapping
        assert "error" not in mapping

    @pytest.mark.asyncio
    async def test_publishes_error_status_with_reason(self) -> None:
        """Error state includes the reason string."""
        mock_redis = AsyncMock()
        await update_account_connection_status(
            mock_redis, state="error", reason="auth_expired"
        )
        call_kwargs = mock_redis.hset.call_args
        mapping = call_kwargs[1]["mapping"]
        assert mapping["state"] == "error"
        assert mapping["error"] == "auth_expired"

    @pytest.mark.asyncio
    async def test_publishes_disconnected_status(self) -> None:
        """Disconnected state is written without error field."""
        mock_redis = AsyncMock()
        await update_account_connection_status(mock_redis, state="disconnected")
        call_kwargs = mock_redis.hset.call_args
        mapping = call_kwargs[1]["mapping"]
        assert mapping["state"] == "disconnected"
        assert "error" not in mapping

    @pytest.mark.asyncio
    async def test_connected_clears_stale_error_field(self) -> None:
        """Connected status removes the stale error field from Redis."""
        mock_redis = AsyncMock()
        await update_account_connection_status(mock_redis, state="connected")
        mock_redis.hdel.assert_awaited_once_with(
            "tastytrade:account_connection", "error"
        )

    @pytest.mark.asyncio
    async def test_error_status_does_not_clear_error_field(self) -> None:
        """Error status preserves the error field."""
        mock_redis = AsyncMock()
        await update_account_connection_status(
            mock_redis, state="error", reason="connection_dropped"
        )
        mock_redis.hdel.assert_not_awaited()


# ---------------------------------------------------------------------------
# consume_positions
# ---------------------------------------------------------------------------


class TestConsumePositions:
    @pytest.mark.asyncio
    async def test_drains_queue_and_publishes(self) -> None:
        """Each Position pulled from the queue is published."""
        queue: asyncio.Queue[Position] = asyncio.Queue()
        mock_publisher = AsyncMock()
        mock_influx = MagicMock()
        stop = asyncio.Event()

        pos = MagicMock(spec=Position)
        queue.put_nowait(pos)

        task = asyncio.create_task(
            consume_positions(queue, mock_publisher, mock_influx, stop)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await task

        mock_publisher.publish_position.assert_awaited_once_with(pos)
        mock_influx.process_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_multiple_positions(self) -> None:
        """Multiple positions are consumed in order."""
        queue: asyncio.Queue[Position] = asyncio.Queue()
        mock_publisher = AsyncMock()
        mock_influx = MagicMock()
        stop = asyncio.Event()

        pos1 = MagicMock(spec=Position)
        pos2 = MagicMock(spec=Position)
        queue.put_nowait(pos1)
        queue.put_nowait(pos2)

        task = asyncio.create_task(
            consume_positions(queue, mock_publisher, mock_influx, stop)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await task

        assert mock_publisher.publish_position.await_count == 2


# ---------------------------------------------------------------------------
# consume_balances
# ---------------------------------------------------------------------------


class TestConsumeBalances:
    @pytest.mark.asyncio
    async def test_drains_queue_and_publishes(self) -> None:
        """Each AccountBalance pulled from the queue is published."""
        queue: asyncio.Queue[AccountBalance] = asyncio.Queue()
        mock_publisher = AsyncMock()
        stop = asyncio.Event()

        bal = MagicMock(spec=AccountBalance)
        queue.put_nowait(bal)

        task = asyncio.create_task(consume_balances(queue, mock_publisher, stop))
        await asyncio.sleep(0.05)
        stop.set()
        await task

        mock_publisher.publish_balance.assert_awaited_once_with(bal)


# ---------------------------------------------------------------------------
# run_account_stream_once
# ---------------------------------------------------------------------------


class TestRunAccountStreamOnce:
    @pytest.mark.asyncio
    async def test_starts_streamer_and_publisher(self) -> None:
        """Verify the orchestrator starts the AccountStreamer and creates a publisher."""
        with (
            patch("tastytrade.accounts.orchestrator.AccountStreamer") as MockStreamer,
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamPublisher"
            ) as MockPublisher,
            patch("tastytrade.accounts.orchestrator.RedisConfigManager") as MockConfig,
            patch("tastytrade.accounts.orchestrator.Credentials"),
            patch("tastytrade.accounts.orchestrator.ReconnectSignal") as MockSignal,
            patch("tastytrade.accounts.orchestrator.TelegrafHTTPEventProcessor"),
        ):
            mock_config = MagicMock()
            mock_config.initialize = MagicMock()
            mock_config.get = MagicMock(return_value="LIVE")
            MockConfig.return_value = mock_config

            mock_signal = AsyncMock()
            mock_signal.wait = AsyncMock(side_effect=asyncio.CancelledError)
            MockSignal.return_value = mock_signal

            mock_streamer = AsyncMock()
            mock_streamer.start = AsyncMock()
            mock_streamer.queues = {
                event_type: asyncio.Queue() for event_type in AccountEventType
            }
            mock_streamer.close = AsyncMock()
            MockStreamer.return_value = mock_streamer
            MockStreamer.instance = None

            mock_publisher = AsyncMock()
            mock_publisher.close = AsyncMock()
            MockPublisher.return_value = mock_publisher

            with pytest.raises(asyncio.CancelledError):
                await run_account_stream_once()

            mock_streamer.start.assert_awaited_once()
            MockPublisher.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_account_stream_error_on_failure(self) -> None:
        """Non-CancelledError exceptions become AccountStreamError."""
        with (
            patch("tastytrade.accounts.orchestrator.AccountStreamer") as MockStreamer,
            patch("tastytrade.accounts.orchestrator.AccountStreamPublisher"),
            patch("tastytrade.accounts.orchestrator.RedisConfigManager") as MockConfig,
            patch("tastytrade.accounts.orchestrator.Credentials"),
            patch("tastytrade.accounts.orchestrator.TelegrafHTTPEventProcessor"),
        ):
            mock_config = MagicMock()
            mock_config.initialize = MagicMock()
            mock_config.get = MagicMock(return_value="LIVE")
            MockConfig.return_value = mock_config

            mock_streamer = AsyncMock()
            mock_streamer.start = AsyncMock(
                side_effect=ConnectionError("WebSocket failed")
            )
            mock_streamer.queues = {
                event_type: asyncio.Queue() for event_type in AccountEventType
            }
            mock_streamer.close = AsyncMock()
            MockStreamer.return_value = mock_streamer
            MockStreamer.instance = None

            with pytest.raises(AccountStreamError) as exc_info:
                await run_account_stream_once()

            assert exc_info.value.was_healthy is False
            assert "WebSocket failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cleanup_on_cancel(self) -> None:
        """Verify streamer and publisher are closed even on cancellation."""
        with (
            patch("tastytrade.accounts.orchestrator.AccountStreamer") as MockStreamer,
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamPublisher"
            ) as MockPublisher,
            patch("tastytrade.accounts.orchestrator.RedisConfigManager") as MockConfig,
            patch("tastytrade.accounts.orchestrator.Credentials"),
            patch("tastytrade.accounts.orchestrator.ReconnectSignal") as MockSignal,
            patch("tastytrade.accounts.orchestrator.TelegrafHTTPEventProcessor"),
        ):
            mock_config = MagicMock()
            mock_config.initialize = MagicMock()
            mock_config.get = MagicMock(return_value="LIVE")
            MockConfig.return_value = mock_config

            mock_signal = AsyncMock()
            mock_signal.wait = AsyncMock(side_effect=asyncio.CancelledError)
            MockSignal.return_value = mock_signal

            mock_streamer = AsyncMock()
            mock_streamer.start = AsyncMock()
            mock_streamer.queues = {
                event_type: asyncio.Queue() for event_type in AccountEventType
            }
            mock_streamer.close = AsyncMock()
            MockStreamer.return_value = mock_streamer
            MockStreamer.instance = None

            mock_publisher = AsyncMock()
            mock_publisher.close = AsyncMock()
            MockPublisher.return_value = mock_publisher

            with pytest.raises(asyncio.CancelledError):
                await run_account_stream_once()

            mock_streamer.close.assert_awaited_once()
            mock_publisher.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# run_account_stream — self-healing wrapper
# ---------------------------------------------------------------------------


class TestRunAccountStream:
    @pytest.mark.asyncio
    async def test_single_shot_mode(self) -> None:
        """auto_reconnect=False runs once and exits."""
        with patch(
            "tastytrade.accounts.orchestrator.run_account_stream_once",
            new_callable=AsyncMock,
        ) as mock_once:
            await run_account_stream(auto_reconnect=False)
            mock_once.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_on_account_stream_error(self) -> None:
        """Unhealthy failures increment attempt counter and retry."""
        call_count = 0

        async def fail_then_succeed(**kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise AccountStreamError("fail", was_healthy=False)

        with patch(
            "tastytrade.accounts.orchestrator.run_account_stream_once",
            side_effect=fail_then_succeed,
        ):
            await run_account_stream(
                auto_reconnect=True,
                base_delay=0.01,
                max_delay=0.05,
            )

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_healthy_failure_resets_counter(self) -> None:
        """was_healthy=True resets the attempt counter to 0."""
        call_count = 0

        async def healthy_fail(**kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise AccountStreamError("fail", was_healthy=True)
            # Third call succeeds

        with patch(
            "tastytrade.accounts.orchestrator.run_account_stream_once",
            side_effect=healthy_fail,
        ):
            await run_account_stream(
                auto_reconnect=True,
                base_delay=0.01,
                max_delay=0.05,
            )

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError is NOT retried — it propagates immediately."""
        with patch(
            "tastytrade.accounts.orchestrator.run_account_stream_once",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ):
            with pytest.raises(asyncio.CancelledError):
                await run_account_stream(auto_reconnect=True)

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self) -> None:
        """After max attempts, the function exits without raising."""
        with patch(
            "tastytrade.accounts.orchestrator.run_account_stream_once",
            new_callable=AsyncMock,
            side_effect=AccountStreamError("fail", was_healthy=False),
        ):
            # Should not raise, just log and exit
            await run_account_stream(
                auto_reconnect=True,
                max_reconnect_attempts=3,
                base_delay=0.01,
                max_delay=0.05,
            )


# ---------------------------------------------------------------------------
# account_failure_trigger_listener
# ---------------------------------------------------------------------------


class TestAccountFailureTriggerListener:
    @pytest.mark.asyncio
    async def test_valid_reason_triggers_reconnect(self) -> None:
        """Valid ReconnectReason triggers reconnect_signal.trigger()."""
        mock_pubsub = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        async def fake_listen():  # type: ignore[no-untyped-def]
            yield {"type": "subscribe", "data": None}
            yield {"type": "message", "data": b"connection_dropped"}

        mock_pubsub.listen = fake_listen

        mock_signal = MagicMock()

        task = asyncio.create_task(
            account_failure_trigger_listener(mock_redis, mock_signal)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_signal.trigger.assert_called_once_with(ReconnectReason.CONNECTION_DROPPED)

    @pytest.mark.asyncio
    async def test_invalid_reason_logs_warning(self) -> None:
        """Invalid value logs a warning and does not trigger reconnect."""
        mock_pubsub = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        async def fake_listen():  # type: ignore[no-untyped-def]
            yield {"type": "subscribe", "data": None}
            yield {"type": "message", "data": b"not_a_valid_reason"}

        mock_pubsub.listen = fake_listen

        mock_signal = MagicMock()

        task = asyncio.create_task(
            account_failure_trigger_listener(mock_redis, mock_signal)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_signal.trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancelled_error_handled_gracefully(self) -> None:
        """CancelledError is caught and pubsub is cleaned up."""
        mock_pubsub = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        async def fake_listen():  # type: ignore[no-untyped-def]
            yield {"type": "subscribe", "data": None}
            # Block forever until cancelled
            await asyncio.sleep(3600)
            yield {"type": "message", "data": b"unreachable"}  # pragma: no cover

        mock_pubsub.listen = fake_listen

        mock_signal = MagicMock()

        task = asyncio.create_task(
            account_failure_trigger_listener(mock_redis, mock_signal)
        )
        await asyncio.sleep(0.05)
        task.cancel()

        # Should not raise — CancelledError is handled gracefully
        await task

        mock_pubsub.unsubscribe.assert_awaited_once_with("account:simulate_failure")
        mock_pubsub.close.assert_awaited_once()
