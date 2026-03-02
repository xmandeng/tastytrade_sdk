import asyncio
import logging
from typing import Optional

from tastytrade.config.enumerations import ReconnectReason

logger = logging.getLogger(__name__)


class ReconnectSignal:
    """Stable reconnection mailbox that outlives ControlHandler across
    reconnection cycles.

    ControlHandler is torn down and recreated every time the pipeline
    reconnects. A direct subscription to ControlHandler would be lost
    on each rebuild. This signal is created once by the Orchestrator,
    passed down through the pipeline, and each new ControlHandler
    instance publishes to the same object.

    Replaces the callback pattern where ControlHandler called back
    into DXLinkManager.trigger_reconnect().
    """

    def __init__(self) -> None:
        self.event: asyncio.Event = asyncio.Event()
        self.reason: Optional[ReconnectReason] = None

    def trigger(self, reason: ReconnectReason) -> None:
        """Signal that reconnection is needed."""
        self.reason = reason
        self.event.set()
        logger.warning("Reconnect signal: %s", reason.value)

    async def wait(self) -> ReconnectReason:
        """Wait for a reconnection signal, return the reason."""
        await self.event.wait()
        self.event.clear()
        return self.reason or ReconnectReason.MANUAL_TRIGGER

    def reset(self) -> None:
        """Reset the signal for the next reconnection cycle."""
        self.event.clear()
        self.reason = None
