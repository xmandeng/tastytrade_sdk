"""Pydantic models for the TastyTrade Account Streamer WebSocket protocol.

Wire protocol uses hyphenated keys (e.g. ``auth-token``, ``request-id``).
All models use ``populate_by_name=True`` so both Python names and aliases work.

Outbound models use ``extra="forbid"`` to catch typos at construction time.
Inbound models use ``extra="allow"`` so new server fields don't break parsing.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class StreamerConnectMessage(BaseModel):
    """Outbound: subscribe to account events on the streamer WebSocket.

    Wire format::

        {"action":"connect","value":["ACCT1"],"auth-token":"<token>","request-id":1}
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    action: str = Field(default="connect")
    value: list[str] = Field(description="Account numbers to subscribe to")
    auth_token: str = Field(alias="auth-token", description="Raw session token")
    request_id: int = Field(alias="request-id", description="Client request ID")


class StreamerHeartbeatMessage(BaseModel):
    """Outbound: keepalive heartbeat to prevent server timeout (60s).

    Wire format::

        {"action":"heartbeat","auth-token":"<token>","request-id":2}
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    action: str = Field(default="heartbeat")
    auth_token: str = Field(alias="auth-token", description="Raw session token")
    request_id: int = Field(alias="request-id", description="Client request ID")


class StreamerResponse(BaseModel):
    """Inbound: server response to connect or heartbeat actions.

    Wire format::

        {"status":"ok","action":"connect","web-socket-session-id":"abc123","request-id":1}
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="allow",
    )

    status: str = Field(description="Response status ('ok' or 'error')")
    action: str = Field(description="Action this responds to")
    web_socket_session_id: Optional[str] = Field(
        default=None,
        alias="web-socket-session-id",
        description="Server-assigned session ID",
    )
    request_id: Optional[int] = Field(
        default=None,
        alias="request-id",
        description="Echoed client request ID",
    )
    message: Optional[str] = Field(
        default=None,
        description="Error message (present when status='error')",
    )


class StreamerEventEnvelope(BaseModel):
    """Inbound: wrapper around a single account event from the streamer.

    Wire format::

        {"type":"CurrentPosition","data":{...},"timestamp":1688595114405,"ws-sequence":42}

    The ``data`` dict is NOT parsed here — it is handed to the appropriate
    TT-28 Pydantic model (``Position`` or ``AccountBalance``) in the streamer.
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="allow",
    )

    type: str = Field(
        description="Event type (e.g. 'CurrentPosition', 'AccountBalance')"
    )
    data: dict[str, Any] = Field(description="Event payload — parsed downstream")
    timestamp: Optional[int] = Field(
        default=None,
        description="Server timestamp in epoch milliseconds",
    )
    ws_sequence: Optional[int] = Field(
        default=None,
        alias="ws-sequence",
        description="WebSocket message sequence number",
    )
