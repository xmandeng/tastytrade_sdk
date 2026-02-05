import logging
from enum import Enum

from tastytrade.messaging.models.events import (
    CandleEvent,
    ControlEvent,
    GreeksEvent,
    ProfileEvent,
    QuoteEvent,
    SummaryEvent,
    TradeEvent,
)

logger = logging.getLogger(__name__)


class Channels(Enum):
    Control = 0
    Profile = 1
    Summary = 3
    Trade = 5
    Quote = 7
    Candle = 9
    Greeks = 11
    Errors = 99


class EventTypes(Enum):
    Control = ControlEvent
    Trade = TradeEvent
    Quote = QuoteEvent
    Greeks = GreeksEvent
    Profile = ProfileEvent
    Summary = SummaryEvent
    Candle = CandleEvent


class SessionState(Enum):
    """Defines possible states for a trading session."""

    INITIALIZING = "initializing"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class DXLinkErrorType(Enum):
    """DXLink protocol error types from AsyncAPI spec."""

    TIMEOUT = "TIMEOUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    BAD_ACTION = "BAD_ACTION"
    UNKNOWN = "UNKNOWN"


# Errors that should trigger reconnection
RECONNECTABLE_ERRORS = {DXLinkErrorType.TIMEOUT, DXLinkErrorType.UNAUTHORIZED}
