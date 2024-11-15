import asyncio
import logging

from tastytrade import Credentials
from tastytrade.session import AsyncSessionHandler
from tastytrade.utilties import setup_logging


async def main():

    try:
        session = await AsyncSessionHandler.create(Credentials(env="Test"))
    finally:
        await session.close_session()


if __name__ == "__main__":
    setup_logging(logging.DEBUG)
    asyncio.run(main())
