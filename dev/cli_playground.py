import asyncio
import logging

from tastytrade import Credentials
from tastytrade.sessions.requests import AsyncSessionHandler
from tastytrade.utils.logging import setup_logging


async def main():

    try:
        session = await AsyncSessionHandler.create(Credentials(env="Live"))
    finally:
        await session.close()


if __name__ == "__main__":
    setup_logging(logging.DEBUG)
    asyncio.run(main())
