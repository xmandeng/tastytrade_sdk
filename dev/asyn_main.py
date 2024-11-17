import asyncio
import logging

from tastytrade import Credentials
from tastytrade.session_async import AsyncSessionHandler
from tastytrade.utilties import setup_logging


async def main():

    try:
        session_handler = await AsyncSessionHandler.create_session(Credentials(env="Test"))
    finally:
        await session_handler.close()


if __name__ == "__main__":
    setup_logging(logging.DEBUG)
    asyncio.run(main())
