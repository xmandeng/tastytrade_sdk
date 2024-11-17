import asyncio
import logging

from tastytrade import Credentials
from tastytrade.async_session import AsyncSessionHandler
from tastytrade.utilties import setup_logging


async def main():
    credentials = Credentials(env="Test")
    session_handler = AsyncSessionHandler(credentials)

    try:
        await session_handler.create_session()
        await session_handler.get_dxlink_token()
    finally:
        await session_handler.close()


if __name__ == "__main__":
    setup_logging(logging.DEBUG)
    asyncio.run(main())
