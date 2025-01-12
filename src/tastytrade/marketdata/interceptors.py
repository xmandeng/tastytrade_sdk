import logging
from collections import defaultdict
from decimal import Decimal
from typing import Awaitable, Callable, Dict, Generic, Set, Type, TypeVar, cast

import polars as pl

from tastytrade.sessions.messaging import EventHandler, MessageQueues
from tastytrade.sessions.models import BaseEvent, Message, ParsedEventType

logger = logging.getLogger(__name__)

EventType = TypeVar("EventType", bound=BaseEvent)


class MarketDataInterceptor(Generic[EventType]):

    @classmethod
    def create(
        cls, queue_manager: MessageQueues, event_model: Type[EventType]
    ) -> "MarketDataInterceptor[EventType]":
        handler_type = type(f"{event_model.__name__.replace('Event', 'Handler')}", (), {})
        existing_handler = next(h for h in queue_manager.handlers if isinstance(h, handler_type))
        interceptor = cls(existing_handler, event_model)
        setattr(existing_handler, "handle_message", interceptor.process)
        return interceptor

    def __init__(self, handler: EventHandler, event_model: Type[EventType]):
        self.handler = handler
        self.event_model = event_model
        self.histories: Dict[str, pl.DataFrame] = defaultdict(
            lambda: pl.DataFrame(
                schema={
                    "timestamp": pl.Datetime(time_zone="America/New_York"),
                    "eventSymbol": pl.String,
                }
            )
        )
        self.callbacks: Dict[str, Set[Callable[[str, pl.DataFrame], Awaitable[None]]]] = {}

    async def process(self, message: Message) -> ParsedEventType:
        try:
            events = await self.handler.handle_message(message)

            if isinstance(events, list):
                for event in cast(list[EventType], events):
                    symbol = event.eventSymbol
                    data = {
                        k: float(v) if isinstance(v, Decimal) else v
                        for k, v in event.model_dump().items()
                    }
                    new_row = pl.DataFrame([data])

                    self.histories[symbol] = pl.concat([self.histories[symbol], new_row]).sort(
                        "timestamp"
                    )

                    if symbol in self.callbacks:
                        for callback in self.callbacks[symbol]:
                            try:
                                await callback(symbol, self.histories[symbol])
                            except Exception as e:
                                logger.error(f"Callback error for {symbol}: {e}")
            return events

        except Exception as e:
            logger.error(f"Error processing event: {e}")
            return await self.handler.handle_message(message)

    def register_callback(
        self, symbol: str, callback: Callable[[str, pl.DataFrame], Awaitable[None]]
    ) -> None:
        if symbol not in self.callbacks:
            self.callbacks[symbol] = set()
        self.callbacks[symbol].add(callback)
