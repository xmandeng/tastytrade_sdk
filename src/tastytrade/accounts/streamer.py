"""AccountStreamer — singleton WebSocket manager for real-time account events.

Connects to the TastyTrade Account Streamer and routes ``CurrentPosition``
and ``AccountBalance`` events into typed asyncio queues.

Protocol notes (validated against production in TT-29 discovery):
    - Auth: raw session token — ``Bearer`` prefix FAILS
    - Event types: ``CurrentPosition`` (not ``Position``), ``AccountBalance``
    - Heartbeat: 20 s client interval, 60 s server timeout
    - No initial state on connect — must REST-hydrate
    - No state replay on reconnect — must REST re-hydrate

Mirrors the singleton / listener / keepalive patterns from ``DXLinkManager``
in ``connections/sockets.py``.
"""

import asyncio
import json
import logging
from types import TracebackType
from typing import Optional, Union

from injector import singleton
from websockets.asyncio.client import ClientConnection, connect

from tastytrade.accounts.client import AccountsClient
from tastytrade.accounts.messages import (
    StreamerConnectMessage,
    StreamerEventEnvelope,
    StreamerHeartbeatMessage,
    StreamerResponse,
)
from tastytrade.accounts.models import AccountBalance, Position
from tastytrade.config.enumerations import AccountEventType, ReconnectReason
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 20
CONNECT_TIMEOUT_SECONDS = 10

STREAMER_URLS: dict[bool, str] = {
    True: "wss://streamer.cert.tastyworks.com",  # sandbox
    False: "wss://streamer.tastyworks.com",  # production
}


@singleton
class AccountStreamer:
    """Singleton WebSocket manager for TastyTrade account-level events.

    Usage::

        async with AccountStreamer(credentials) as streamer:
            await streamer.start()
            event = await streamer.queues[AccountEventType.CURRENT_POSITION].get()
    """

    instance: Optional["AccountStreamer"] = None

    websocket: Optional[ClientConnection] = None
    session: Optional[AsyncSessionHandler] = None
    listener_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
    keepalive_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def __new__(
        cls,
        credentials: Optional[Credentials] = None,
    ) -> "AccountStreamer":
        if cls.instance is None:
            cls.instance = object.__new__(cls)
        return cls.instance

    def __init__(
        self,
        credentials: Optional[Credentials] = None,
    ) -> None:
        if not hasattr(self, "initialized"):
            self.credentials = credentials
            self.queues: dict[
                AccountEventType, asyncio.Queue[Union[Position, AccountBalance]]
            ] = {event_type: asyncio.Queue() for event_type in AccountEventType}

            # Reconnection state
            self.reconnect_event: asyncio.Event = asyncio.Event()
            self.should_reconnect: bool = True
            self.reconnect_reason: Optional[ReconnectReason] = None

            # Request ID counter for outbound messages
            self.request_id: int = 0

            self.initialized = True

    # --- Async context manager -------------------------------------------

    async def __aenter__(self) -> "AccountStreamer":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    # --- Public API -------------------------------------------------------

    async def start(self) -> None:
        """Connect, authenticate, REST-hydrate, and begin listening."""
        if self.credentials is None:
            raise ValueError("Cannot start AccountStreamer without credentials")

        credentials = self.credentials

        # 1. REST login
        self.session = await AsyncSessionHandler.create(credentials)
        session_token: str = str(self.session.session.headers.get("Authorization", ""))
        account_number: str = credentials.account_number

        # 2. Validate account
        client = AccountsClient(self.session)
        await client.validate_account_number(account_number)

        # 3. Open WebSocket
        ws_url = STREAMER_URLS[credentials.is_sandbox]
        ws = await asyncio.wait_for(
            connect(ws_url),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        self.websocket = ws
        logger.info("WebSocket connected to %s", ws_url)

        # 4. Send connect / subscribe
        self.request_id += 1
        connect_msg = StreamerConnectMessage(
            value=[account_number],
            auth_token=session_token,  # type: ignore[call-arg]
            request_id=self.request_id,  # type: ignore[call-arg]
        )
        await ws.send(connect_msg.model_dump_json(by_alias=True))

        # 5. Await connect response
        raw_response = await asyncio.wait_for(
            ws.recv(),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        response = StreamerResponse.model_validate_json(raw_response)
        if response.status != "ok":
            raise ConnectionError(
                f"Account streamer connect failed: {response.message}"
            )
        logger.info(
            "Account streamer authenticated (session=%s)",
            response.web_socket_session_id,
        )

        # 6. REST-hydrate initial state into queues
        await self.hydrate(client, account_number)

        # 7. Start background tasks
        self.listener_task = asyncio.create_task(
            self.socket_listener(), name="account_streamer_listener"
        )
        self.keepalive_task = asyncio.create_task(
            self.send_keepalives(), name="account_streamer_keepalive"
        )

    async def hydrate(self, client: AccountsClient, account_number: str) -> None:
        """REST-fetch positions + balance and enqueue as initial state."""
        positions = await client.get_positions(account_number)
        for pos in positions:
            self.queues[AccountEventType.CURRENT_POSITION].put_nowait(pos)
        logger.info("Hydrated %d positions into queue", len(positions))

        balance = await client.get_balances(account_number)
        self.queues[AccountEventType.ACCOUNT_BALANCE].put_nowait(balance)
        logger.info("Hydrated balance into queue")

    async def close(self) -> None:
        """Cancel tasks, close WebSocket + REST session, reset singleton."""
        self.should_reconnect = False

        tasks_to_cancel = [
            ("Listener", self.listener_task),
            ("Keepalive", self.keepalive_task),
        ]
        await asyncio.gather(
            *[
                self._cancel_task(name, task)
                for name, task in tasks_to_cancel
                if task is not None
            ]
        )
        self.listener_task = None
        self.keepalive_task = None

        if self.websocket is not None:
            await self.websocket.close()
            self.websocket = None

        if self.session is not None:
            await self.session.close()
            self.session = None

        self.initialized = False
        logger.info("AccountStreamer closed and cleaned up")

    def trigger_reconnect(self, reason: ReconnectReason) -> None:
        """Signal that reconnection is needed."""
        self.reconnect_reason = reason
        self.reconnect_event.set()

    async def wait_for_reconnect_signal(self) -> ReconnectReason:
        """Wait for reconnection signal, return reason."""
        await self.reconnect_event.wait()
        self.reconnect_event.clear()
        return self.reconnect_reason or ReconnectReason.MANUAL_TRIGGER

    # --- Internal: listener & keepalive -----------------------------------

    async def socket_listener(self) -> None:
        """Listen for WebSocket messages and route events to queues."""
        assert self.websocket is not None
        try:
            async for message in self.websocket:
                try:
                    raw = json.loads(message)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse message: %s", e)
                    continue

                # Heartbeat / connect responses have an "action" key
                if "action" in raw:
                    logger.debug(
                        "Response: action=%s status=%s",
                        raw.get("action"),
                        raw.get("status"),
                    )
                    continue

                # Batched events have a "results" key
                if "results" in raw:
                    for event_data in raw["results"]:
                        self._handle_event(event_data)
                elif "type" in raw:
                    self._handle_event(raw)
                else:
                    logger.warning("Unknown message format: %s", str(raw)[:200])

        except asyncio.CancelledError:
            logger.info("Account streamer listener stopped")
        except Exception as e:
            logger.error("Account streamer listener error: %s", e)
            if self.should_reconnect:
                self.trigger_reconnect(ReconnectReason.CONNECTION_DROPPED)

    async def send_keepalives(self) -> None:
        """Send heartbeat messages every HEARTBEAT_INTERVAL_SECONDS."""
        assert self.websocket is not None
        assert self.session is not None
        session_token: str = str(self.session.session.headers.get("Authorization", ""))
        ws = self.websocket
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                self.request_id += 1
                heartbeat = StreamerHeartbeatMessage(
                    auth_token=session_token,  # type: ignore[call-arg]
                    request_id=self.request_id,  # type: ignore[call-arg]
                )
                await ws.send(heartbeat.model_dump_json(by_alias=True))
                logger.debug("Heartbeat sent (request-id=%d)", self.request_id)
        except asyncio.CancelledError:
            logger.info("Account streamer keepalive stopped")
        except Exception as e:
            logger.error("Error sending heartbeat: %s", e)
            if self.should_reconnect:
                self.trigger_reconnect(ReconnectReason.CONNECTION_DROPPED)

    def _handle_event(self, raw: dict) -> None:  # type: ignore[type-arg]
        """Parse a single event envelope and route to the appropriate queue."""
        try:
            envelope = StreamerEventEnvelope.model_validate(raw)
        except Exception as e:
            logger.warning("Failed to parse event envelope: %s", e)
            return

        parsed = self.parse_event(envelope.type, envelope.data)
        if parsed is None:
            return

        try:
            event_type = AccountEventType(envelope.type)
        except ValueError:
            logger.warning("Unknown account event type: %s", envelope.type)
            return

        self.queues[event_type].put_nowait(parsed)
        logger.debug(
            "Queued %s event (ws-sequence=%s)",
            envelope.type,
            envelope.ws_sequence,
        )

    @staticmethod
    def parse_event(
        event_type: str,
        data: dict,  # type: ignore[type-arg]
    ) -> Union[Position, AccountBalance, None]:
        """Parse event data into the corresponding TT-28 Pydantic model."""
        try:
            if event_type == AccountEventType.CURRENT_POSITION:
                return Position.model_validate(data)
            elif event_type == AccountEventType.ACCOUNT_BALANCE:
                return AccountBalance.model_validate(data)
            else:
                logger.warning("Unknown event type for parsing: %s", event_type)
                return None
        except Exception as e:
            logger.warning("Failed to parse %s event: %s", event_type, e)
            return None

    # --- Internal: task management ----------------------------------------

    @staticmethod
    async def _cancel_task(name: str, task: asyncio.Task) -> None:  # type: ignore[type-arg]
        try:
            task.cancel()
            await task
        except asyncio.CancelledError:
            logger.info("%s task cancelled", name)
