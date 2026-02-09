"""Tests for EventHandler log severity on validation errors (TT-16)."""

import asyncio
import logging

import pytest

from tastytrade.common.exceptions import MessageProcessingError
from tastytrade.config.enumerations import Channels
from tastytrade.messaging.handlers import EventHandler
from tastytrade.messaging.models.messages import Message


def make_quote_message(
    bid_price: object,
    ask_price: object,
    bid_size: float = 100.0,
    ask_size: float = 200.0,
) -> Message:
    """Build a Message that the Quote EventHandler can process."""
    return Message(
        type="FEED_DATA",
        channel=Channels.Quote.value,
        headers={},
        data=[["AAPL", bid_price, ask_price, bid_size, ask_size]],
    )


@pytest.fixture
def quote_handler() -> EventHandler:
    return EventHandler(channel=Channels.Quote)


@pytest.mark.asyncio
async def test_valid_quote_processes_without_error(
    quote_handler: EventHandler,
) -> None:
    """Sanity check: a valid quote message should process cleanly."""
    msg = make_quote_message(bid_price=185.0, ask_price=185.5)
    result = await quote_handler.handle_message(msg)
    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 1
    event = result[0]
    assert hasattr(event, "askPrice")
    assert event.askPrice == 185.5  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_none_ask_price_raises_message_processing_error(
    quote_handler: EventHandler,
) -> None:
    """A None askPrice should raise MessageProcessingError, not crash the handler."""
    msg = make_quote_message(bid_price=185.0, ask_price=None)
    with pytest.raises(MessageProcessingError, match="Skipped invalid event"):
        await quote_handler.handle_message(msg)


@pytest.mark.asyncio
async def test_validation_error_logs_warning_not_error(
    quote_handler: EventHandler, caplog: pytest.LogCaptureFixture
) -> None:
    """TT-16: Validation errors must log at WARNING, not ERROR."""
    msg = make_quote_message(bid_price=185.0, ask_price=None)

    with caplog.at_level(logging.DEBUG, logger="tastytrade.messaging.handlers"):
        with pytest.raises(MessageProcessingError):
            await quote_handler.handle_message(msg)

    handler_records = [
        r for r in caplog.records if r.name == "tastytrade.messaging.handlers"
    ]

    # No ERROR-level records should exist for a recoverable validation error
    error_records = [r for r in handler_records if r.levelno >= logging.ERROR]
    assert error_records == [], (
        f"Expected no ERROR logs for a recoverable validation error, "
        f"got: {[r.message for r in error_records]}"
    )

    # At least one WARNING-level record should exist
    warning_records = [r for r in handler_records if r.levelno == logging.WARNING]
    assert (
        len(warning_records) >= 1
    ), "Expected at least one WARNING log for skipped event"
    assert any("Skipped invalid event" in r.message for r in warning_records)


@pytest.mark.asyncio
async def test_queue_listener_continues_after_validation_error(
    quote_handler: EventHandler, caplog: pytest.LogCaptureFixture
) -> None:
    """The queue listener must recover from validation errors and keep processing."""
    queue: asyncio.Queue[dict] = asyncio.Queue()

    bad_raw = {
        "type": "FEED_DATA",
        "channel": Channels.Quote.value,
        "data": [["AAPL", 185.0, None, 100.0, 200.0]],
    }
    good_raw = {
        "type": "FEED_DATA",
        "channel": Channels.Quote.value,
        "data": [["AAPL", 186.0, 186.5, 100.0, 200.0]],
    }
    await queue.put(bad_raw)
    await queue.put(good_raw)

    EventHandler.stop_listener.clear()
    with caplog.at_level(logging.DEBUG, logger="tastytrade.messaging.handlers"):
        task = asyncio.create_task(quote_handler.queue_listener(queue))
        await asyncio.wait_for(queue.join(), timeout=5.0)

        EventHandler.stop_listener.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Should have recorded exactly 1 error in metrics
    assert quote_handler.metrics.error_count == 1
    # Should have processed both messages (2 total)
    assert quote_handler.metrics.total_messages == 2

    # The error log should be WARNING, not ERROR
    handler_records = [
        r for r in caplog.records if r.name == "tastytrade.messaging.handlers"
    ]
    error_records = [r for r in handler_records if r.levelno >= logging.ERROR]
    assert error_records == [], (
        f"Expected no ERROR logs from queue_listener recovery, "
        f"got: {[r.message for r in error_records]}"
    )
