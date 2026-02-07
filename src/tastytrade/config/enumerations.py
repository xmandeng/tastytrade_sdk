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


class ReconnectReason(Enum):
    """Reasons for triggering connection reconnection.

    Used for typed signaling in the reconnection flow, enabling
    both production error handling and test injection.
    """

    AUTH_EXPIRED = "auth_expired"  # Token expired mid-session
    CONNECTION_DROPPED = "connection_dropped"  # WebSocket closed unexpectedly
    TIMEOUT = "timeout"  # No response within threshold
    PROTOCOL_ERROR = "protocol_error"  # Invalid message from server
    MANUAL_TRIGGER = "manual_trigger"  # Test injection / manual trigger
