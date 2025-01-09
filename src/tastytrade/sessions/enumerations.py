import logging
from enum import Enum

from tastytrade.sessions.models import (
    GreeksEvent,
    ProfileEvent,
    QuoteEvent,
    SummaryEvent,
    TradeEvent,
)

logger = logging.getLogger(__name__)


class Channels(Enum):
    Control = 0
    Trades = 1
    Quotes = 3
    Greeks = 5
    Profile = 7
    Summary = 9
    Errors = 99


class EventTypes(Enum):
    Trades = TradeEvent
    Quotes = QuoteEvent
    Greeks = GreeksEvent
    Profile = ProfileEvent
    Summary = SummaryEvent


class SessionState(Enum):
    """Defines possible states for a trading session."""

    INITIALIZING = "initializing"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    DISCONNECTED = "disconnected"
    ERROR = "error"
