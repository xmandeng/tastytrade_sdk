"""Tests for account stream orchestrator — self-healing lifecycle."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tastytrade.accounts.orchestrator import (
    AccountStreamError,
    _consume_balances,
    _consume_positions,
    run_account_stream,
    run_account_stream_once,
)
from tastytrade.accounts.models import AccountBalance, Position
from tastytrade.config.enumerations import AccountEventType


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
# _consume_positions
# ---------------------------------------------------------------------------


class TestConsumePositions:
    @pytest.mark.asyncio
    async def test_drains_queue_and_publishes(self) -> None:
        """Each Position pulled from the queue is published."""
        queue: asyncio.Queue[Position] = asyncio.Queue()
        mock_publisher = AsyncMock()

        pos = MagicMock(spec=Position)
        queue.put_nowait(pos)

        task = asyncio.create_task(_consume_positions(queue, mock_publisher))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        mock_publisher.publish_position.assert_awaited_once_with(pos)

    @pytest.mark.asyncio
    async def test_handles_multiple_positions(self) -> None:
        """Multiple positions are consumed in order."""
        queue: asyncio.Queue[Position] = asyncio.Queue()
        mock_publisher = AsyncMock()

        pos1 = MagicMock(spec=Position)
        pos2 = MagicMock(spec=Position)
        queue.put_nowait(pos1)
        queue.put_nowait(pos2)

        task = asyncio.create_task(_consume_positions(queue, mock_publisher))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_publisher.publish_position.await_count == 2


# ---------------------------------------------------------------------------
# _consume_balances
# ---------------------------------------------------------------------------


class TestConsumeBalances:
    @pytest.mark.asyncio
    async def test_drains_queue_and_publishes(self) -> None:
        """Each AccountBalance pulled from the queue is published."""
        queue: asyncio.Queue[AccountBalance] = asyncio.Queue()
        mock_publisher = AsyncMock()

        bal = MagicMock(spec=AccountBalance)
        queue.put_nowait(bal)

        task = asyncio.create_task(_consume_balances(queue, mock_publisher))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
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
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamer"
            ) as MockStreamer,
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamPublisher"
            ) as MockPublisher,
            patch(
                "tastytrade.accounts.orchestrator.RedisConfigManager"
            ) as MockConfig,
            patch("tastytrade.accounts.orchestrator.Credentials"),
        ):
            mock_config = MagicMock()
            mock_config.initialize = MagicMock()
            mock_config.get = MagicMock(return_value="LIVE")
            MockConfig.return_value = mock_config

            mock_streamer = AsyncMock()
            mock_streamer.start = AsyncMock()
            mock_streamer.queues = {
                AccountEventType.CURRENT_POSITION: asyncio.Queue(),
                AccountEventType.ACCOUNT_BALANCE: asyncio.Queue(),
            }
            mock_streamer.close = AsyncMock()
            mock_streamer.wait_for_reconnect_signal = AsyncMock(
                side_effect=asyncio.CancelledError
            )
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
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamer"
            ) as MockStreamer,
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamPublisher"
            ),
            patch(
                "tastytrade.accounts.orchestrator.RedisConfigManager"
            ) as MockConfig,
            patch("tastytrade.accounts.orchestrator.Credentials"),
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
                AccountEventType.CURRENT_POSITION: asyncio.Queue(),
                AccountEventType.ACCOUNT_BALANCE: asyncio.Queue(),
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
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamer"
            ) as MockStreamer,
            patch(
                "tastytrade.accounts.orchestrator.AccountStreamPublisher"
            ) as MockPublisher,
            patch(
                "tastytrade.accounts.orchestrator.RedisConfigManager"
            ) as MockConfig,
            patch("tastytrade.accounts.orchestrator.Credentials"),
        ):
            mock_config = MagicMock()
            mock_config.initialize = MagicMock()
            mock_config.get = MagicMock(return_value="LIVE")
            MockConfig.return_value = mock_config

            mock_streamer = AsyncMock()
            mock_streamer.start = AsyncMock()
            mock_streamer.queues = {
                AccountEventType.CURRENT_POSITION: asyncio.Queue(),
                AccountEventType.ACCOUNT_BALANCE: asyncio.Queue(),
            }
            mock_streamer.close = AsyncMock()
            mock_streamer.wait_for_reconnect_signal = AsyncMock(
                side_effect=asyncio.CancelledError
            )
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
