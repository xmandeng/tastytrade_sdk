import asyncio
import json
import logging
from dataclasses import dataclass

from injector import inject
from websockets.asyncio.client import ClientConnection, connect

from tastytrade import Credentials
from tastytrade.messages import MessageHandler
from tastytrade.session import AsyncSessionHandler
from tastytrade.utilties import setup_logging

logger = logging.getLogger(__name__)


@dataclass
class DXLinkConfig:
    keepalive_timeout: int = 60
    version: str = "0.1-DXF-JS/0.3.0"
    default_channel: int = 1
    reconnect_attempts: int = 3  # for later use
    reconnect_delay: int = 5  # for later use


class DXLinkClient:

    @classmethod
    @inject
    def run(cls, credentials: Credentials):
        instance = cls(MessageHandler())
        asyncio.run(instance.main(credentials))

    def __init__(
        self,
        message_handler: MessageHandler = MessageHandler(),
        config: DXLinkConfig = DXLinkConfig(),
    ):
        self.config = config
        self.message_handler = message_handler

    async def main(self, credentials: Credentials):
        session = await AsyncSessionHandler.create(credentials)

        async with connect(session.session.headers["dxlink-url"]) as websocket:

            try:

                listener_task = asyncio.create_task(self.channel_listener(websocket))

                await self.setup_connection(websocket)
                await self.authorize_connection(websocket, session.session.headers["token"])
                await self.request_channel(websocket, self.config.default_channel)
                await self.setup_feed(websocket, self.config.default_channel)
                await self.subscribe_to_feed(websocket, self.config.default_channel)

                await listener_task

            except asyncio.CancelledError:
                logger.info("Listener task was cancelled")
            except Exception as e:
                logger.error("An error occurred: %s", e)
            finally:
                await session.close_session()

    async def setup_connection(self, websocket: ClientConnection):
        setup = json.dumps(
            {
                "type": "SETUP",
                "channel": 0,
                "version": self.config.version,
                "keepaliveTimeout": self.config.keepalive_timeout,
                "acceptKeepaliveTimeout": 60,
            }
        )
        await asyncio.wait_for(websocket.send(setup), timeout=5)

    async def channel_listener(self, websocket: ClientConnection):
        while True:
            try:
                await self.parse_message(websocket)

            except asyncio.TimeoutError:
                print("Receiving operation timed out\n")
                break
            except Exception as e:
                print(f"An error occurred: {e}\n")
                break

    async def parse_message(self, websocket: ClientConnection):
        try:
            reply = await asyncio.wait_for(websocket.recv(), timeout=45)
            reply_data = json.loads(reply)
            await self.message_handler.route_message(reply_data, websocket)

        except asyncio.TimeoutError:
            print("Receiving operation timed out\n")
        except Exception as e:
            print(f"An error occurred: {e}\n")

    async def authorize_connection(self, websocket: ClientConnection, token: str):
        authorize = json.dumps({"type": "AUTH", "channel": 0, "token": token})
        await asyncio.wait_for(websocket.send(authorize), timeout=5)

    async def request_channel(self, websocket: ClientConnection, channel: int):
        channel_request = json.dumps(
            {
                "type": "CHANNEL_REQUEST",
                "channel": channel,
                "service": "FEED",
                "parameters": {"contract": "AUTO"},
            }
        )
        await asyncio.wait_for(websocket.send(channel_request), timeout=5)

    async def keepalive(self, websocket: ClientConnection):
        await websocket.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
        logger.debug("KEEPALIVE [local]")

    async def setup_feed(self, websocket: ClientConnection, channel: int):

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

        await websocket.send(feed)

    async def subscribe_to_feed(self, websocket: ClientConnection, channel: int):
        feed_subscription = json.dumps(
            {
                "type": "FEED_SUBSCRIPTION",
                "channel": channel,
                "reset": True,
                "add": [
                    # {"type": "Trade", "symbol": "BTC/USD:CXTALP"},
                    {"type": "Quote", "symbol": "BTC/USD:CXTALP"},
                    # {"type": "Profile", "symbol": "BTC/USD:CXTALP"},
                    # {"type": "Summary", "symbol": "BTC/USD:CXTALP"},
                    # {"type": "Trade", "symbol": "SPY"},
                    # {"type": "TradeETH", "symbol": "SPY"},  # WHY SPXY on TradeETH
                    # {"type": "Quote", "symbol": "SPX"},
                    # {"type": "Profile", "symbol": "SPY"},
                    # {"type": "Summary", "symbol": "SPY"},
                    # {"type": "Quote", "symbol": ".SPX241220P5885"},
                    # {"type": "Greeks", "symbol": ".SPX241220P5885"},
                    # {"type": "Quote", "symbol": ".SPXW241118C5885"},
                    # {"type": "Greeks", "symbol": ".SPXW241118C5885"},
                    {"type": "Quote", "symbol": ".SPXW241119P5895"},
                    {"type": "Greeks", "symbol": ".SPXW241119P5895"},
                    {"type": "Quote", "symbol": ".SPXW241119P5885"},
                    {"type": "Greeks", "symbol": ".SPXW241119P5885"},
                    {"type": "Quote", "symbol": ".SPXW241119P5905"},
                    {"type": "Greeks", "symbol": ".SPXW241119P5905"},
                ],
            }
        )

        await websocket.send(feed_subscription)


if __name__ == "__main__":
    setup_logging(logging.INFO)
    asyncio.run(DXLinkClient(MessageHandler()).main(Credentials("Test")))
