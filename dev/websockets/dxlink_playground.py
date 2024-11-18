#!/usr/bin/env python

"""Client using the asyncio API."""

import asyncio
import json
import logging
from datetime import datetime

from websockets.asyncio.client import connect

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

    setup = json.dumps(
        {
            "type": "SETUP",
            "channel": 0,
            "version": "0.1-DXF-JS/0.3.0",
            "keepaliveTimeout": 60,
            "acceptKeepaliveTimeout": 60,
        }
    )

    channel_request = json.dumps(
        {
            "type": "CHANNEL_REQUEST",
            "channel": 1,
            "service": "FEED",
            "parameters": {"contract": "AUTO"},
        }
    )

    authorize = json.dumps(
        {"type": "AUTH", "channel": 0, "token": session.session.headers["token"]}
    )

    try:
        async with connect(session.session.headers["dxlink-url"]) as websocket:

            # Send SETUP message
            await asyncio.wait_for(websocket.send(setup), timeout=5)
            reply = await asyncio.wait_for(websocket.recv(), timeout=5)
            reply_data = json.loads(reply)
            logger.info("%s", reply_data.get("type"))

            reply = await asyncio.wait_for(websocket.recv(), timeout=5)
            reply_data = json.loads(reply)
            logger.info("%s:%s", reply_data.get("type"), "" or reply_data.get("state"))

            # Send AUTH message
            await asyncio.wait_for(websocket.send(authorize), timeout=5)
            reply = await asyncio.wait_for(websocket.recv(), timeout=5)
            reply_data = json.loads(reply)
            logger.info("%s:%s", reply_data.get("type"), "" or reply_data.get("state"))

            # Send CHANNEL_REQUEST message
            await asyncio.wait_for(websocket.send(channel_request), timeout=5)

            while True:
                try:
                    reply = await asyncio.wait_for(websocket.recv(), timeout=45)
                    reply_data = json.loads(reply)
                    logger.info("%s", reply_data.get("type"))
                    print(f"{json.dumps(json.loads(reply), indent=2)}\n")
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


if __name__ == "__main__":
    asyncio.run(main())
