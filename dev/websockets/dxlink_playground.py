#!/usr/bin/env python

"""Client using the asyncio API."""

import asyncio
import json
import logging
from datetime import datetime

from websockets.asyncio.client import connect

from tastytrade.utilties import setup_logging


def now_iso():
    return datetime.now().isoformat()


async def hello():
    message = json.dumps(
        {
            "type": "SETUP",
            "channel": 0,
            "version": "0.1-DXF-JS/0.3.0",
            "keepaliveTimeout": 60,
            "acceptKeepaliveTimeout": 60,
        }
    )

    try:
        async with connect("wss://tasty-openapi-ws.dxfeed.com/realtime") as websocket:
            print("Lets get this started ...\n")

            print("Send message", str(now_iso()), message, "\n")
            await asyncio.wait_for(websocket.send(message), timeout=45)

            while True:
                try:
                    reply = await asyncio.wait_for(websocket.recv(), timeout=45)
                    print("Received:", str(now_iso()), reply)
                    print(f"\n{json.dumps(json.loads(reply), indent=2)}\n")
                except asyncio.TimeoutError:
                    print("Receiving operation timed out\n")
                    break
                except Exception as e:
                    print(f"An error occurred: {e}\n")
                    break

    except asyncio.TimeoutError:
        print("Operation timed out after 45 seconds\n")
    except Exception as e:
        print(f"An error occurred: {e}\n")


if __name__ == "__main__":
    setup_logging(logging.INFO)
    asyncio.run(hello())
