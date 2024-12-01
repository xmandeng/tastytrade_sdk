import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Awaitable, Callable, Dict, Optional, Protocol, Set, cast

import polars as pl

from tastytrade.sessions.messaging import QuotesHandler
from tastytrade.sessions.models import MARKET_TZ, Message, ParsedEventType, QuoteEvent

logger = logging.getLogger(__name__)


class MessageHandler(Protocol):
    """Protocol defining the interface for message handlers."""

    async def handle_message(self, message: Message) -> ParsedEventType: ...


class MessageInterceptor(ABC):
    """Abstract base class for message stream interceptors."""

    def __init__(self, handler: MessageHandler):
        self.handler = handler
        self.is_active = False
        # Store handler method as attribute to allow reassignment
        self.handle_message_method = self.process

    @abstractmethod
    async def process(self, message: Message) -> ParsedEventType:
        """Process the intercepted message."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup resources used by the interceptor."""
        pass


class QuoteManagerInterceptor(MessageInterceptor):
    """Interceptor that manages price history tracking."""

    def __init__(self, handler: MessageHandler):
        super().__init__(handler)
        self.price_histories: Dict[str, pl.DataFrame] = {}
        self.callbacks: Dict[str, Set[Callable[[str, pl.DataFrame], Awaitable[None]]]] = {}
        logger.info("QuoteManager interceptor initialized")

    def initialize_symbol_df(self, symbol: str) -> None:
        """Initialize price history tracking for a symbol."""
        if symbol not in self.price_histories:
            self.price_histories[symbol] = pl.DataFrame(
                schema={
                    "timestamp": pl.Datetime(time_zone=MARKET_TZ.key),
                    "mid_price": pl.Float64,
                    "bid_price": pl.Float64,
                    "ask_price": pl.Float64,
                    "bid_size": pl.Float64,
                    "ask_size": pl.Float64,
                }
            )
            logger.info(f"Initialized price history tracking for {symbol}")

    async def process(self, message: Message) -> ParsedEventType:
        """Process the message through the chain.

        # Original flow

        QuotesHandler -> Other Components

        # With interceptor

        QuotesHandler -> QuoteManagerInterceptor -> Other Components
                              |
                              v
                        Store Price History
        """
        try:
            # First let the original handler process
            events = await self.handler.handle_message(message)

            # Process quotes - we can safely cast since we know this is the quotes channel
            if events:
                await self.process_quotes(cast(list[QuoteEvent], events))

            return events  # Return events whether None or populated

        except Exception as e:
            logger.error(f"Error in quote manager processing: {e}")
            # Fall back to original handler
            return await self.handler.handle_message(message)

    async def process_quotes(self, quotes: list[QuoteEvent]) -> None:
        """Update price histories with new quotes."""
        for quote in quotes:
            symbol = quote.eventSymbol
            self.initialize_symbol_df(symbol)

            new_row = pl.DataFrame(
                [
                    {
                        "timestamp": quote.timestamp,
                        "mid_price": float((quote.bidPrice + quote.askPrice) / 2),
                        "bid_price": float(quote.bidPrice),
                        "ask_price": float(quote.askPrice),
                        "bid_size": float(quote.bidSize) if quote.bidSize else 0.0,
                        "ask_size": float(quote.askPrice) if quote.askPrice else 0.0,
                    }
                ]
            )

            self.price_histories[symbol] = pl.concat([self.price_histories[symbol], new_row]).sort(
                "timestamp"
            )

            if symbol in self.callbacks:
                for callback in self.callbacks[symbol]:
                    try:
                        await callback(symbol, self.price_histories[symbol])
                    except Exception as e:
                        logger.error(f"Error in callback for {symbol}: {e}")

    async def cleanup(self) -> None:
        """Cleanup interceptor resources."""
        self.callbacks.clear()
        logger.info("Quote manager interceptor cleaned up")


class QuoteManager:
    """Manages real-time quote data streams with explicit message interception."""

    def __init__(self, quotes_handler: QuotesHandler):
        self.quotes_handler = cast(MessageHandler, quotes_handler)
        self.interceptor = QuoteManagerInterceptor(self.quotes_handler)

        # Store original method reference
        self.original_handle_message = quotes_handler.handle_message

        # Bind the interceptor's process method to the handler instance
        quotes_handler.handle_message = self.interceptor.process  # type: ignore

        logger.info("QuoteManager initialized with explicit interceptor")

    def register_callback(
        self, symbol: str, callback: Callable[[str, pl.DataFrame], Awaitable[None]]
    ) -> None:
        """Register a callback for symbol updates."""
        if symbol not in self.interceptor.callbacks:
            self.interceptor.callbacks[symbol] = set()
        self.interceptor.callbacks[symbol].add(callback)
        self.interceptor.initialize_symbol_df(symbol)
        logger.debug(f"Registered callback for {symbol}")

    def unregister_callback(
        self, symbol: str, callback: Callable[[str, pl.DataFrame], Awaitable[None]]
    ) -> None:
        """Remove a symbol update callback."""
        if symbol in self.interceptor.callbacks:
            self.interceptor.callbacks[symbol].discard(callback)
            if not self.interceptor.callbacks[symbol]:
                del self.interceptor.callbacks[symbol]

    def get_price_history(
        self,
        symbol: str,
        lookback: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> pl.DataFrame:
        """Get price history for a symbol."""
        if symbol not in self.interceptor.price_histories:
            raise KeyError(f"No price history available for {symbol}")

        df = self.interceptor.price_histories[symbol]

        if start_time:
            df = df.filter(pl.col("timestamp") >= start_time)
        if end_time:
            df = df.filter(pl.col("timestamp") <= end_time)
        if lookback:
            df = df.tail(lookback)

        return df

    async def cleanup(self) -> None:
        """Restore original handler and cleanup resources."""
        await self.interceptor.cleanup()
        self.quotes_handler.handle_message = self.original_handle_message  # type: ignore
        logger.info("Restored original quotes handler")
