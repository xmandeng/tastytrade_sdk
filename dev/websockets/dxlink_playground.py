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

SETUP = json.dumps(
    {
        "type": "SETUP",
        "channel": 0,
        "version": "0.1-DXF-JS/0.3.0",
        "keepaliveTimeout": 60,
        "acceptKeepaliveTimeout": 60,
    }
)

CHANNEL_REQUEST = json.dumps(
    {"type": "CHANNEL_REQUEST", "channel": 3, "service": "FEED", "parameters": {"contract": "AUTO"}}
)


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def main():
    setup_logging(logging.INFO)

    session = await AsyncSessionHandler.create(Credentials(env="Live"))
    token = session.session.headers["token"]
    # finally:
    #     await session.close_session()

    authorize = json.dumps({"type": "AUTH", "channel": 0, "token": token})

    try:
        async with connect("wss://tasty-openapi-ws.dxfeed.com/realtime") as websocket:
            print("Lets get this started ...\n")

            await asyncio.wait_for(websocket.send(SETUP), timeout=5)
            reply = await asyncio.wait_for(websocket.recv(), timeout=5)

            print("Received:", str(timestamp()))
            print(f"{json.dumps(json.loads(reply), indent=2)}\n")

            reply = await asyncio.wait_for(websocket.recv(), timeout=5)
            print("Received:", str(timestamp()))
            print(f"{json.dumps(json.loads(reply), indent=2)}\n")

            await asyncio.wait_for(websocket.send(authorize), timeout=5)
            reply = await asyncio.wait_for(websocket.recv(), timeout=5)
            print("Received:", str(timestamp()))
            print(f"{json.dumps(json.loads(reply), indent=2)}\n")

            await asyncio.wait_for(websocket.send(CHANNEL_REQUEST), timeout=5)

            while True:
                try:
                    reply = await asyncio.wait_for(websocket.recv(), timeout=45)
                    print("Received:", str(timestamp()))
                    print(f"{json.dumps(json.loads(reply), indent=2)}\n")
                except asyncio.TimeoutError:
                    print("Receiving operation timed out\n")
                    break
                except Exception as e:
                    print(f"An error occurred: {e}\n")
                    break

            await session.close_session()

    except asyncio.TimeoutError:
        print("Operation timed out after 45 seconds\n")
    except Exception as e:
        print(f"An error occurred: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
