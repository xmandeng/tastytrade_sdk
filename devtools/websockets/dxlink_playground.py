#!/usr/bin/env python

import asyncio
import json
import logging

from websockets.asyncio.client import ClientConnection, connect

from tastytrade.logging import setup_logging
from tastytrade.sessions import Credentials
from tastytrade.sessions.requests import AsyncSessionHandler

logger = logging.getLogger(__name__)

ENV = "Live"

credentials = Credentials(env=ENV)


async def setup_connection(websocket: ClientConnection):
    setup = json.dumps(
        {
            "type": "SETUP",
            "channel": 0,
            "version": "0.1-DXF-JS/0.3.0",
            "keepaliveTimeout": 60,
            "acceptKeepaliveTimeout": 60,
        }
    )
    await asyncio.wait_for(websocket.send(setup), timeout=5)


async def authorize_connection(websocket: ClientConnection, token: str):
    authorize = json.dumps({"type": "AUTH", "channel": 0, "token": token})
    await asyncio.wait_for(websocket.send(authorize), timeout=5)


async def request_channel(websocket: ClientConnection, channel: int):
    channel_request = json.dumps(
        {
            "type": "CHANNEL_REQUEST",
            "channel": channel,
            "service": "FEED",
            "parameters": {"contract": "AUTO"},
        }
    )
    await asyncio.wait_for(websocket.send(channel_request), timeout=5)


async def channel_listener(websocket: ClientConnection):
    while True:
        try:
            await parse_message(websocket)

        except asyncio.TimeoutError:
            print("Receiving operation timed out\n")
            break
        except Exception as e:
            print(f"An error occurred: {e}\n")
            break


async def keepalive(websocket: ClientConnection):
    await websocket.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
    logger.debug("KEEPALIVE [local]")


async def setup_feed(websocket: ClientConnection, channel: int):

    feed = json.dumps(
        {
            "type": "FEED_SETUP",
            "channel": channel,
            "acceptAggregationPeriod": 0.1,
            "acceptDataFormat": "COMPACT",
            "acceptEventFields": {
                "Trade": ["eventType", "eventSymbol", "price", "dayVolume", "size"],
                "TradeETH": ["eventType", "eventSymbol", "price", "dayVolume", "size"],
                "Quote": ["eventType", "eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize"],
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


async def subscribe_to_feed(websocket: ClientConnection, channel: int):
    feed_subscription = json.dumps(
        {
            "type": "FEED_SUBSCRIPTION",
            "channel": channel,
            "reset": True,
            "add": [
                # {"type": "Trade", "symbol": "BTC/USD:CXTALP"},
                # {"type": "Quote", "symbol": "BTC/USD:CXTALP"},
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


async def parse_message(websocket: ClientConnection):
    try:
        reply = await asyncio.wait_for(websocket.recv(), timeout=45)
        reply_data = json.loads(reply)

    except asyncio.TimeoutError:
        print("Receiving operation timed out\n")
    except Exception as e:
        print(f"An error occurred: {e}\n")

    match message_type := reply_data.get("type"):
        case "SETUP":
            logger.info("%s", message_type)

        case "AUTH_STATE":
            auth_state = reply_data.get("state")
            logger.info("%s:%s", message_type, auth_state)

        case "CHANNEL_REQUEST":
            logger.info("Received CHANNEL_REQUEST message")
            # Handle CHANNEL_REQUEST message

        case "CHANNEL_OPENED":
            logger.info("Received CHANNEL_OPENED message")
            # Handle CHANNEL_OPENED message

        case "FEED_CONFIG":
            logger.info("Received FEED_CONFIG message")

        case "FEED_DATA":
            # TODO Add a data handler
            logger.debug("Received FEED_DATA message\n%s", json.dumps(reply_data, indent=2))

        case "KEEPALIVE":
            logger.info("Received KEEPALIVE message")
            await keepalive(websocket)

        case "ERROR":
            logger.error("%s: %s", reply_data.get("error"), reply_data.get("message"))

        case _:
            logger.info("Received unknown message type: %s", message_type)
            # Handle unknown message type


async def main():
    session = await AsyncSessionHandler.create(credentials)

    async with connect(session.session.headers["dxlink-url"]) as websocket:

        try:
            await setup_connection(websocket)
            await authorize_connection(websocket, session.session.headers["token"])
            await request_channel(websocket, 1)
            await setup_feed(websocket, 1)
            await subscribe_to_feed(websocket, 1)

            await asyncio.create_task(channel_listener(websocket))

        except asyncio.CancelledError:
            logger.info("Listener task was cancelled")
        except Exception as e:
            logger.error("An error occurred: %s", e)
        finally:
            await session.close_session()


if __name__ == "__main__":
    setup_logging(logging.DEBUG)
    asyncio.run(main())
