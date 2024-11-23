import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import aiohttp
import requests
from injector import inject, singleton
from requests import Session
from websockets.asyncio.client import ClientConnection, connect

from tastytrade import Credentials
from tastytrade.exceptions import validate_async_response, validate_response
from tastytrade.messages import MessageHandler

QueryParams = Optional[dict[str, Any]]

logger = logging.getLogger(__name__)


class SessionHandler:
    """Tastytrade session."""

    session = Session()
    is_active: bool = False

    @classmethod
    @inject
    def create(cls, credentials: Credentials) -> "SessionHandler":
        instance = cls(credentials)
        instance.create_session(credentials)
        instance.get_dxlink_token()
        return instance

    @inject
    def __init__(self, credentials: Credentials) -> None:
        self.base_url = credentials.base_url

        self.session.headers.update(
            {
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def request(
        self, method: str, url: str, params: QueryParams = None, **kwargs
    ) -> requests.Response:
        # TODO Add URL params
        response = self.session.request(
            method, url, headers=self.session.headers, params=params, **kwargs
        )

        validate_response(response)

        return response

    def create_session(self, credentials: Credentials) -> None:
        """Login to the Tastytrade API."""
        if self.is_session_active():
            logger.warning("Session already active")
            return

        response = self.request(
            method="POST",
            url=self.base_url + "/sessions",
            data=json.dumps(
                {
                    "login": credentials.login,
                    "password": credentials.password,
                    "remember-me": credentials.remember_me,
                }
            ),
        )

        self.session.headers.update({"Authorization": response.json()["data"]["session-token"]})

        logger.info("Session created")
        self.is_active = True

    def close(self) -> None:
        """Close the Tastytrade session."""
        response = self.session.request("DELETE", self.base_url + "/sessions")

        if validate_response(response):
            logger.info("Session closed")
            self.is_active = False
        else:
            logger.error(f"Failed to close session [{response.status_code}]")
            raise Exception(f"Failed to close session [{response.status_code}]")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active

    def get_dxlink_token(self) -> None:
        """Get the quote token."""
        response = self.session.request(
            method="GET",
            url=self.base_url + "/api-quote-tokens",
        )

        self.session.headers.update({"dxlink-url": response.json()["data"]["dxlink-url"]})
        self.session.headers.update({"token": response.json()["data"]["token"]})


@inject
class AsyncSessionHandler:
    """Tastytrade session handler for API interactions."""

    @classmethod
    async def create(cls, credentials: Credentials) -> "AsyncSessionHandler":
        instance = cls(credentials)
        await instance.create_session(credentials)
        await instance.get_dxlink_token()
        return instance

    def __init__(self, credentials: Credentials) -> None:
        self.base_url: str = credentials.base_url
        self.session: aiohttp.ClientSession = aiohttp.ClientSession(
            headers={
                "User-Agent": "my_tastytrader_sdk",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.is_active: bool = False

    async def create_session(self, credentials: Credentials) -> None:
        """Create and authenticate a session with Tastytrade API."""
        if self.is_active:
            logger.warning("Session already active")
            return

        async with self.session.post(
            url=f"{self.base_url}/sessions",
            json={
                "login": credentials.login,
                "password": credentials.password,
                "remember-me": credentials.remember_me,
            },
        ) as response:
            response_data = await response.json()

            if validate_async_response(response):
                logger.info("Session created successfully")

            self.session.headers.update({"Authorization": response_data["data"]["session-token"]})
            self.is_active = True

    async def get_dxlink_token(self) -> None:
        """Get the dxlink token."""
        async with self.session.get(url=f"{self.base_url}/api-quote-tokens") as response:
            response_data = await response.json()

            if validate_async_response(response):
                logger.debug("Retrieved dxlink token")

            self.session.headers.update({"dxlink-url": response_data["data"]["dxlink-url"]})
            self.session.headers.update({"token": response_data["data"]["token"]})

    async def close(self) -> None:
        """Close the session and cleanup resources."""
        if self.session:
            await self.session.close()
            self.is_active = False
            logger.info("Session closed")

    def is_session_active(self) -> bool:
        """Check if the session is active."""
        return self.is_active


@singleton
class WebSocketManager:

    sessions: dict[AsyncSessionHandler, "WebSocketManager"] = {}
    listener_task: asyncio.Task

    def __new__(cls, session):
        if session not in cls.sessions:
            cls.sessions[session] = super(WebSocketManager, cls).__new__(cls)
        return cls.sessions[session]

    def __init__(
        self,
        session: AsyncSessionHandler,
        message_handler: MessageHandler = MessageHandler(),
    ):
        self.session = session
        self.url = session.session.headers["dxlink-url"]
        self.token = session.session.headers["token"]
        self.message_handler = message_handler
        self.websocket: ClientConnection
        self.channels: dict[int, str] = {}
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb, *args, **kwargs):
        await self.close()

    async def open(self):
        self.websocket = await connect(self.url)
        self.listener_task = asyncio.create_task(self.websocket_listener())

        try:
            await self.setup_connection()
            await self.authorize_connection()

        except Exception as e:
            logger.error(f"Error during setup or authorization: {e}")
            await self.websocket.close()
            self.websocket = None
            raise e

    async def close(self):
        if self.session in self.sessions:
            del self.sessions[self.session]

        if hasattr(self, "websocket"):
            await asyncio.sleep(0.25)
            if hasattr(self, "listener_task"):
                try:
                    # Tip: Must cancel listener_task then catch CancelledError
                    self.listener_task.cancel()
                    await self.listener_task

                except asyncio.CancelledError:
                    logger.info("Listener task was cancelled")

            await self.websocket.close()
            self.websocket = None
            logger.info("Websocket closed")
        else:
            logger.warning("Websocket - No active connection to close")

    async def setup_connection(self):
        setup = json.dumps(
            {
                "type": "SETUP",
                "channel": 0,
                "version": "0.1-DXF-JS/0.3.0",
                "keepaliveTimeout": 60,
                "acceptKeepaliveTimeout": 60,
            }
        )
        await asyncio.wait_for(self.websocket.send(setup), timeout=5)

    async def authorize_connection(self):
        authorize = json.dumps({"type": "AUTH", "channel": 0, "token": self.token})
        await asyncio.wait_for(self.websocket.send(authorize), timeout=5)

    async def websocket_listener(self):
        while True:
            try:
                await self.parse_message()
            except asyncio.CancelledError:
                logger.info("LISTENER - Stopped")
                break
            except Exception as e:
                logger.error(f"LISTENER ERROR: {e}")
                break

    async def parse_message(self) -> None:
        try:
            reply = await asyncio.wait_for(self.websocket.recv(), timeout=45)
            await self.message_handler.route_message(json.loads(reply), self.websocket)

        except asyncio.TimeoutError:
            print("Receiving operation timed out\n")
        except Exception as e:
            print(f"An error occurred: {e}\n")


@dataclass
class DXLinkConfig:
    keepalive_timeout: int = 60
    version: str = "0.1-DXF-JS/0.3.0"
    channel_assignment: int = 1
    reconnect_attempts: int = 3  # for later use
    reconnect_delay: int = 5  # for later use


class DXLinkClient:

    # @classmethod
    # @inject
    # def run(cls, credentials: Credentials):
    #     instance = cls(MessageHandler())
    #     asyncio.run(instance.connect(credentials))

    def __init__(
        self,
        websocket_manager: WebSocketManager,
        message_handler: MessageHandler = MessageHandler(),
        config: DXLinkConfig = DXLinkConfig(),
    ):
        self.websocket = websocket_manager.websocket
        self.config = config
        self.message_handler = message_handler

    async def request_channel(self, channel: int):
        channel_request = json.dumps(
            {
                "type": "CHANNEL_REQUEST",
                "channel": channel,
                "service": "FEED",
                "parameters": {"contract": "AUTO"},
            }
        )
        await asyncio.wait_for(self.websocket.send(channel_request), timeout=5)

    async def setup_feed(self, channel: int):
        feed = json.dumps(
            {
                "type": "FEED_SETUP",
                "channel": channel,
                "acceptAggregationPeriod": 0.1,
                "acceptDataFormat": "COMPACT",
                "acceptEventFields": {
                    "Trade": ["eventType", "eventSymbol", "price", "dayVolume", "size"],
                    "TradeETH": ["eventType", "eventSymbol", "price", "dayVolume", "size"],
                    "Quote": [
                        "eventType",
                        "eventSymbol",
                        "bidPrice",
                        "askPrice",
                        "bidSize",
                        "askSize",
                    ],
                    "Greeks": [
                        "eventType",
                        "eventSymbol",
                        "volatility",
                        "delta",
                        "gamma",
                        "theta",
                        "rho",
                        "vega",
                    ],
                    "Profile": [
                        "eventType",
                        "eventSymbol",
                        "description",
                        "shortSaleRestriction",
                        "tradingStatus",
                        "statusReason",
                        "haltStartTime",
                        "haltEndTime",
                        "highLimitPrice",
                        "lowLimitPrice",
                        "high52WeekPrice",
                        "low52WeekPrice",
                    ],
                    "Summary": [
                        "eventType",
                        "eventSymbol",
                        "openInterest",
                        "dayOpenPrice",
                        "dayHighPrice",
                        "dayLowPrice",
                        "prevDayClosePrice",
                    ],
                },
            }
        )

        await self.websocket.send(feed)

    async def subscribe_to_feed(self, channel: int):
        feed_subscription = json.dumps(
            {
                "type": "FEED_SUBSCRIPTION",
                "channel": channel,
                "reset": True,
                "add": [
                    {"type": "Trade", "symbol": "BTC/USD:CXTALP"},
                    {"type": "Quote", "symbol": "BTC/USD:CXTALP"},
                    {"type": "Profile", "symbol": "BTC/USD:CXTALP"},
                    {"type": "Summary", "symbol": "BTC/USD:CXTALP"},
                    {"type": "Trade", "symbol": "SPY"},
                    {"type": "TradeETH", "symbol": "SPY"},  # WHY SPXY on TradeETH
                    {"type": "Quote", "symbol": "SPX"},
                    {"type": "Profile", "symbol": "SPY"},
                    {"type": "Summary", "symbol": "SPY"},
                    {"type": "Quote", "symbol": "SPX"},
                    {"type": "Quote", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5895"},
                    {"type": "Greeks", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5895"},
                    {"type": "Quote", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5885"},
                    {"type": "Greeks", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5885"},
                    {"type": "Quote", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5905"},
                    {"type": "Greeks", "symbol": f".SPXW{datetime.now().strftime('%y%m%d')}P5905"},
                ],
            }
        )

        await self.websocket.send(feed_subscription)


async def main():
    # TODO Get rid of this
    try:
        session = await AsyncSessionHandler.create(Credentials(env="Test"))
    finally:
        await session.close()


# if __name__ == "__main__":
# Test AsyncSession
# setup_logging(logging.DEBUG)
# asyncio.run(main())

# Test DXLinkClient
# setup_logging(logging.INFO)
# asyncio.run(DXLinkClient(MessageHandler()).connect(Credentials("Live")))
