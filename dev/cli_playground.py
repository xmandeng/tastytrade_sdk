import asyncio
import logging

from tastytrade.logging import setup_logging
from tastytrade.sessions import Credentials
from tastytrade.sessions.requests import AsyncSessionHandler


async def main():

    try:
        session = await AsyncSessionHandler.create(Credentials(env="Live"))
    finally:
        await session.close()


if __name__ == "__main__":
    setup_logging(logging.DEBUG)
    asyncio.run(main())
