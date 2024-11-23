from typing import Callable, Dict, Optional

from tastytrade.models import (
    EventType,
    GreeksEvent,
    ProfileEvent,
    QuoteEvent,
    SummaryEvent,
    TradeEvent,
)


class EventParser:
    """Parses raw event data into structured event objects."""

    def __init__(self) -> None:
        self.parsers: Dict[str, Callable[[list], EventType]] = {
            "Trade": self.parse_trade,
            "TradeETH": self.parse_trade,  # ? Uses same structure as Trade
            "Quote": self.parse_quote,
            "Greeks": self.parse_greeks,
            "Profile": self.parse_profile,
            "Summary": self.parse_summary,
        }

    async def route_event(self, event_data: list) -> Optional[EventType]:
        """Parse raw event data into appropriate event object."""
        event_type = event_data[0]

        if parser := self.parsers.get(event_type):
            return await self.parse_event(parser, event_data[1])
        return None

    async def parse_event(self, parser: Callable[[list], EventType], data: list) -> EventType:
        return parser(data)

    def parse_trade(self, data: list) -> TradeEvent:
        return TradeEvent(
            event_type=data[0],
            symbol=data[1],
            price=data[2],
            day_volume=data[3],
            size=data[4],
        )

    def parse_quote(self, data: list) -> QuoteEvent:
        return QuoteEvent(
            event_type=data[0],
            symbol=data[1],
            bid_price=data[2],
            ask_price=data[3],
            bid_size=data[4],
            ask_size=data[5],
        )

    def parse_greeks(self, data: list) -> GreeksEvent:
        return GreeksEvent(
            event_type=data[0],
            symbol=data[1],
            volatility=data[2],
            delta=data[3],
            gamma=data[4],
            theta=data[5],
            rho=data[6],
            vega=data[7],
        )

    def parse_profile(self, data: list) -> ProfileEvent:
        return ProfileEvent(
            event_type=data[0],
            symbol=data[1],
            description=data[2],
            short_sale_restriction=data[3],
            trading_status=data[4],
            status_reason=data[5],
            halt_start_time=data[6],
            halt_end_time=data[7],
            high_limit_price=data[8],
            low_limit_price=data[9],
            high_52_week_price=data[10],
            low_52_week_price=data[11],
        )

    def parse_summary(self, data: list) -> SummaryEvent:
        return SummaryEvent(
            event_type=data[0],
            symbol=data[1],
            open_interest=data[2],
            day_open_price=data[3],
            day_high_price=data[4],
            day_low_price=data[5],
            prev_day_close_price=data[6],
        )
