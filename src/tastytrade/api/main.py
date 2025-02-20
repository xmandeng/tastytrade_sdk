import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from tastytrade.common.logging import setup_logging
from tastytrade.connections import Credentials
from tastytrade.connections.sockets import DXLinkManager

"""Example curl requests:

# Subscribe to feed
curl -X POST "http://localhost:8000/subscribe/feed" \
     -H "Content-Type: application/json" \
     -d '{"symbols": ["SPY", "AAPL"]}'

# Unsubscribe to feed
curl -X POST "http://localhost:8000/unsubscribe/feed" \
     -H "Content-Type: application/json" \
     -d '{"symbols": ["SPY", "AAPL"]}'

# Subscribe to candles
curl -X POST "http://localhost:8000/subscribe/candles" \
     -H "Content-Type: application/json" \
     -d '{"symbol": "SPY", "interval": "5m"}'
"""

# Configure logging
logger = logging.getLogger(__name__)

setup_logging(
    level=logging.INFO if not os.getenv("TASTYTRADE_API_DEBUG") else logging.DEBUG,
    console=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global dxlink_manager
    async with initialization_lock:
        if dxlink_manager is None:
            try:
                credentials = Credentials(env="Live")
                dxlink_manager = DXLinkManager()
                await dxlink_manager.open(credentials)
                logger.info("DXLink manager initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize DXLink manager: {e}")
                raise

    yield

    # Shutdown
    if dxlink_manager:
        await dxlink_manager.close()
        logger.info("DXLink manager closed")


app = FastAPI(title="TastyTrade API", description="REST API for TastyTrade SDK", lifespan=lifespan)

# Global DXLink manager instance
dxlink_manager: Optional[DXLinkManager] = None
initialization_lock = asyncio.Lock()


class SymbolSubscription(BaseModel):
    symbols: List[str]


class CandleSubscription(BaseModel):
    symbol: str
    interval: str
    from_time: Optional[datetime] = None


class SubscriptionStatus(BaseModel):
    """Pydantic model for subscription status."""

    symbol: str
    subscribe_time: datetime
    interval: Optional[str] = None
    active: bool
    last_update: Optional[datetime] = None
    metadata: Dict = {}


# @app.get("/health")
# async def health_check():
#     """Check the health of the API and DXLink connection."""
#     if not dxlink_manager:
#         raise HTTPException(status_code=503, detail="DXLink manager not initialized")

#     try:
#         # Get websocket status based on authorization state
#         ws_connected = (
#             dxlink_manager.websocket is not None and dxlink_manager.auth_state == "AUTHORIZED"
#         )  # Use the auth state we track

#         # Get router status
#         router_active = dxlink_manager.router is not None

#         return {
#             "status": "healthy" if ws_connected and router_active else "degraded",
#             "websocket_connected": ws_connected,
#             "router_active": router_active,
#             "timestamp": datetime.now().isoformat(),
#         }
#     except Exception as e:
#         logger.error(f"Health check failed: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


@app.get("/subscriptions")
async def get_subscriptions() -> Dict[str, SubscriptionStatus]:
    """Get all active subscriptions and their status."""
    if not dxlink_manager:
        raise HTTPException(status_code=503, detail="DXLink manager not initialized")

    try:
        subscriptions = await dxlink_manager.get_active_subscriptions()
        return {
            key: SubscriptionStatus(
                symbol=sub.symbol,
                subscribe_time=sub.subscribe_time,
                interval=sub.interval,
                active=sub.active,
                last_update=sub.last_update,
                metadata=sub.metadata,
            )
            for key, sub in subscriptions.items()
        }
    except Exception as e:
        logger.error(f"Error getting subscriptions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/subscribe/feed")
async def subscribe(subscription: SymbolSubscription, background_tasks: BackgroundTasks):
    """Subscribe to market data feed for specified symbols."""
    if not dxlink_manager:
        raise HTTPException(status_code=503, detail="DXLink manager not initialized")

    try:
        background_tasks.add_task(dxlink_manager.subscribe, subscription.symbols)
        return {
            "status": "success",
            "message": f"Subscribing to {len(subscription.symbols)} symbols",
        }
    except Exception as e:
        logger.error(f"Error subscribing to feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/unsubscribe/feed")
async def unsubscribe(subscription: SymbolSubscription, background_tasks: BackgroundTasks):
    """Unsubscribe from market data feed for specified symbols."""
    if not dxlink_manager:
        raise HTTPException(status_code=503, detail="DXLink manager not initialized")

    try:
        background_tasks.add_task(dxlink_manager.unsubscribe, subscription.symbols)
        return {
            "status": "success",
            "message": f"Unsubscribing from {len(subscription.symbols)} symbols",
        }
    except Exception as e:
        logger.error(f"Error unsubscribing from feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/subscribe/candles")
async def subscribe_to_candles(subscription: CandleSubscription, background_tasks: BackgroundTasks):
    """Subscribe to candle data for a specified symbol and interval."""
    if not dxlink_manager:
        raise HTTPException(status_code=503, detail="DXLink manager not initialized")

    try:
        from_time = subscription.from_time or datetime.now()
        background_tasks.add_task(
            dxlink_manager.subscribe_to_candles,
            symbol=subscription.symbol,
            interval=subscription.interval,
            from_time=from_time,
        )
        return {
            "status": "success",
            "message": f"Subscribing to candles for {subscription.symbol} with {subscription.interval} interval",
        }
    except Exception as e:
        logger.error(f"Error subscribing to candles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/unsubscribe/candles")
async def unsubscribe_from_candles(
    subscription: CandleSubscription, background_tasks: BackgroundTasks
):
    """Unsubscribe from candle data for a specified symbol and interval."""
    if not dxlink_manager:
        raise HTTPException(status_code=503, detail="DXLink manager not initialized")

    try:
        background_tasks.add_task(
            dxlink_manager.unsubscribe_to_candles,
            symbol=subscription.symbol,
            interval=subscription.interval,
        )
        return {
            "status": "success",
            "message": f"Unsubscribing from candles for {subscription.symbol} with {subscription.interval} interval",
        }
    except Exception as e:
        logger.error(f"Error unsubscribing from candles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/subscriptions")
async def clear_all_subscriptions(background_tasks: BackgroundTasks):
    """Clear all active subscriptions."""
    if not dxlink_manager:
        raise HTTPException(status_code=503, detail="DXLink manager not initialized")

    try:
        # Get current subscriptions
        subscriptions = await dxlink_manager.get_active_subscriptions()

        # Group subscriptions by type
        feed_symbols = []
        candle_subscriptions = []

        for sub in subscriptions.values():
            if sub.interval:
                candle_subscriptions.append(
                    CandleSubscription(symbol=sub.symbol, interval=sub.interval)
                )
            else:
                feed_symbols.append(sub.symbol)

        # Unsubscribe from all feeds
        if feed_symbols:
            background_tasks.add_task(dxlink_manager.unsubscribe, feed_symbols)

        # Unsubscribe from all candles
        for sub in candle_subscriptions:
            background_tasks.add_task(
                dxlink_manager.unsubscribe_to_candles, symbol=sub.symbol, interval=sub.interval
            )

        return {
            "status": "success",
            "message": f"Clearing {len(feed_symbols)} feeds and {len(candle_subscriptions)} candle subscriptions",
        }
    except Exception as e:
        logger.error(f"Error clearing subscriptions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def start():
    """Entry point for the API when run through poetry."""
    import uvicorn

    uvicorn.run("tastytrade.api.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    # When running the file directly, use this simpler approach
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
