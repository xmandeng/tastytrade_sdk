#!/usr/bin/env python

"""Client using the asyncio API."""

import asyncio
import json
import logging
from datetime import datetime

from websockets.asyncio.client import ClientConnection, connect

from tastytrade import Credentials
from tastytrade.session import AsyncSessionHandler
from tastytrade.utilties import setup_logging

logger = logging.getLogger(__name__)


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def main():
    setup_logging(logging.INFO)
    logger.info("\nLets get this started ...\n")

    session = await AsyncSessionHandler.create(Credentials(env="Test"))

    try:
        async with connect(session.session.headers["dxlink-url"]) as websocket:
            await setup_connection(websocket)
            await authorize_connection(websocket, session.session.headers["token"])
            await request_channel(websocket, 1)

            while True:
                try:
                    reply = await asyncio.wait_for(websocket.recv(), timeout=45)
                    reply_data = json.loads(reply)

                    if reply_data.get("type") == "KEEPALIVE":
                        logger.info("KEEPALIVE [remote]")
                        await keepalive(websocket)
                    else:
                        print(f"{json.dumps(json.loads(reply), indent=2)}")
                        logger.info("%s", reply_data.get("type"))

                except asyncio.TimeoutError:
                    print("Receiving operation timed out\n")
                    break
                except Exception as e:
                    print(f"An error occurred: {e}\n")
                    break

            await session.close_session()

    except asyncio.TimeoutError as e:
        print(f"Operation timed: {e}\n")
    except KeyboardInterrupt as k:
        logger.info(f"KeyboardInterrupt: {k}\n")
    except Exception as e:
        print(f"An error occurred: {e}\n")


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
    reply = await asyncio.wait_for(websocket.recv(), timeout=5)
    reply_data = json.loads(reply)
    logger.info("%s", reply_data.get("type"))

    reply = await asyncio.wait_for(websocket.recv(), timeout=5)
    reply_data = json.loads(reply)
    logger.info("%s:%s", reply_data.get("type"), "" or reply_data.get("state"))


async def authorize_connection(websocket: ClientConnection, token: str):

    authorize = json.dumps({"type": "AUTH", "channel": 0, "token": token})

    await asyncio.wait_for(websocket.send(authorize), timeout=5)
    reply = await asyncio.wait_for(websocket.recv(), timeout=5)
    reply_data = json.loads(reply)
    logger.info("%s:%s", reply_data.get("type"), "" or reply_data.get("state"))


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

    try:
        reply = await asyncio.wait_for(websocket.recv(), timeout=45)
        reply_data = json.loads(reply)
        logger.info("%s", reply_data.get("type"))
        print(f"{json.dumps(json.loads(reply), indent=2)}")
    except asyncio.TimeoutError:
        print("Receiving operation timed out\n")
    except Exception as e:
        print(f"An error occurred: {e}\n")


async def channel_listener(websocket: ClientConnection):
    while True:
        try:
            reply = await asyncio.wait_for(websocket.recv(), timeout=45)
            reply_data = json.loads(reply)
            logger.info("%s", reply_data.get("type"))
            print(f"{json.dumps(json.loads(reply), indent=2)}")

        except asyncio.TimeoutError:
            print("Receiving operation timed out\n")
            break


async def keepalive(websocket: ClientConnection):
    await websocket.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
    logger.info("KEEPALIVE [local]")


async def setup_feed(websocket: ClientConnection):

    feed = json.dumps(
        {
            "type": "FEED_SETUP",
            "channel": 3,
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

    await websocket.send(json.dumps(feed))


if __name__ == "__main__":
    asyncio.run(main())
