"""Candle snapshot completion tracker.

Monitors DXLink eventFlags bitmask on CandleEvent to detect when historical
snapshot delivery is complete for each subscribed symbol. Used to synchronize
gap-fill operations that depend on data being in InfluxDB.

DXLink eventFlags protocol:
    Bit 0 (0x01) = TX_PENDING    — more events coming in this transaction
    Bit 1 (0x02) = REMOVE_EVENT  — event removal (used in empty snapshots)
    Bit 2 (0x04) = SNAPSHOT_BEGIN — first event in a snapshot
    Bit 3 (0x08) = SNAPSHOT_END  — last event in a snapshot
    Bit 4 (0x10) = SNAPSHOT_SNIP — snapshot truncated (also signals end)
"""

import asyncio
import logging

from tastytrade.messaging.models.events import BaseEvent, CandleEvent

logger = logging.getLogger(__name__)

TX_PENDING = 0x01
REMOVE_EVENT = 0x02
SNAPSHOT_BEGIN = 0x04
SNAPSHOT_END = 0x08
SNAPSHOT_SNIP = 0x10


class CandleSnapshotTracker:
    """Tracks candle snapshot completion across multiple symbols.

    Attach to the Candle EventHandler via add_processor(). Register expected
    symbols before subscriptions are sent, then consume ``completions`` queue
    to react as each symbol finishes, or await ``wait_for_completion()`` to
    block until all snapshots have landed.

    Attributes:
        completions: asyncio.Queue that receives each event symbol string
            as its snapshot completes. Drain this to trigger per-symbol work
            (e.g. gap-fill) without waiting for all symbols.
    """

    name: str = "candle_snapshot_tracker"

    def __init__(self) -> None:
        self.pending_symbols: set[str] = set()
        self.completed_symbols: set[str] = set()
        self.completions: asyncio.Queue[str] = asyncio.Queue()
        self._all_complete = asyncio.Event()

    def register_symbol(self, event_symbol: str) -> None:
        """Register a symbol to track for snapshot completion.

        Args:
            event_symbol: The candle event symbol (e.g., "AAPL{=d}").
        """
        self.pending_symbols.add(event_symbol)
        self._all_complete.clear()

    def process_event(self, event: BaseEvent) -> None:
        """Check each CandleEvent for snapshot-end flags.

        Non-candle events and events for unregistered symbols are ignored.
        """
        if not isinstance(event, CandleEvent):
            return

        flags = event.eventFlags
        if flags is None:
            return

        symbol = event.eventSymbol
        if symbol not in self.pending_symbols:
            return

        if flags & (SNAPSHOT_END | SNAPSHOT_SNIP):
            self.pending_symbols.discard(symbol)
            self.completed_symbols.add(symbol)
            self.completions.put_nowait(symbol)
            logger.debug(
                "Snapshot complete for %s (flags=0x%02x) — %d remaining",
                symbol,
                flags,
                len(self.pending_symbols),
            )

            if not self.pending_symbols:
                logger.info(
                    "All %d candle snapshots received", len(self.completed_symbols)
                )
                self._all_complete.set()

    async def wait_for_completion(self, timeout: float) -> set[str]:
        """Block until all registered symbols have completed their snapshots.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            Set of symbols that did NOT complete within the timeout.
            Empty set means all snapshots arrived successfully.
        """
        if not self.pending_symbols:
            return set()

        try:
            await asyncio.wait_for(self._all_complete.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Snapshot timeout after %.1fs — %d/%d symbols incomplete: %s",
                timeout,
                len(self.pending_symbols),
                len(self.pending_symbols) + len(self.completed_symbols),
                sorted(self.pending_symbols),
            )

        return set(self.pending_symbols)

    def reset(self) -> None:
        """Clear all tracking state."""
        self.pending_symbols.clear()
        self.completed_symbols.clear()
        self._all_complete.clear()
        # Drain the queue
        while not self.completions.empty():
            self.completions.get_nowait()
