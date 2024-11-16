import asyncio

from tastytrade import Credentials
from tastytrade.async_session import AsyncSessionHandler


async def main():
    credentials = Credentials(env="Test")
    session_handler = AsyncSessionHandler(credentials)

    try:
        await session_handler.create_session()
        # Do your async operations here
    finally:
        await session_handler.close()


if __name__ == "__main__":
    asyncio.run(main())
