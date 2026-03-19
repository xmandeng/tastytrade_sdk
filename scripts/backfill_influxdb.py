"""One-shot backfill of historical account events into InfluxDB.

Run once with: uv run python scripts/backfill_influxdb.py

Backfills:
  1. Orders — from REST API via get_orders()
  2. Trade chains — from Redis HGETALL
  3. Entry credits — computed from transactions + positions via LIFO replay
  4. Positions — from REST API via get_positions()

No AccountBalance (excluded per TT-83 design). Complex orders deferred.
"""

import asyncio
import logging
import sys

import redis.asyncio as aioredis  # type: ignore[import-untyped]

from tastytrade.accounts.client import AccountsClient
from tastytrade.accounts.models import OrderStatus, TradeChain
from tastytrade.accounts.publisher import AccountStreamPublisher
from tastytrade.accounts.transactions import (
    TransactionsClient,
    compute_entry_credits_for_positions,
)
from tastytrade.config import RedisConfigManager
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.messaging.processors.influxdb import TelegrafHTTPEventProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # --- Init config + credentials ---
    config = RedisConfigManager(env_file=".env")
    config.initialize()
    credentials = Credentials(config, env="Live")
    session = await AsyncSessionHandler.create(credentials)

    accounts_client = AccountsClient(session)
    transactions_client = TransactionsClient(session)
    influx = TelegrafHTTPEventProcessor(
        url=config.get("INFLUX_DB_URL"),
        token=config.get("INFLUX_DB_TOKEN"),
        org=config.get("INFLUX_DB_ORG"),
        bucket=config.get("INFLUX_DB_BUCKET"),
    )

    account = credentials.account_number
    counts: dict[str, int] = {}

    try:
        # --- 1. Backfill filled orders ---
        logger.info("Backfilling filled orders...")
        all_orders = await accounts_client.get_orders(account)
        filled_orders = [o for o in all_orders if o.status == OrderStatus.FILLED]
        for order in filled_orders:
            influx.process_event(order.for_influx())  # type: ignore[arg-type]
        counts["orders"] = len(filled_orders)
        logger.info(
            "Wrote %d filled orders to InfluxDB (of %d total)",
            len(filled_orders),
            len(all_orders),
        )

        # --- 2. Backfill trade chains from Redis ---
        logger.info("Backfilling trade chains from Redis...")
        redis_client: aioredis.Redis = aioredis.Redis(  # type: ignore[type-arg]
            host=config.get("REDIS_HOST", "localhost"),
            port=int(config.get("REDIS_PORT", "6379")),
        )
        raw_chains = await redis_client.hgetall(AccountStreamPublisher.TRADE_CHAINS_KEY)
        chain_count = 0
        for raw in raw_chains.values():
            chain = TradeChain.model_validate_json(raw)
            influx.process_event(chain.for_influx())  # type: ignore[arg-type]
            chain_count += 1
        counts["trade_chains"] = chain_count
        logger.info("Wrote %d trade chains to InfluxDB", chain_count)
        await redis_client.aclose()  # type: ignore[attr-defined]

        # --- 3. Backfill entry credits ---
        logger.info("Backfilling entry credits...")
        transactions = await transactions_client.get_transactions(account)
        positions = await accounts_client.get_positions(account)
        position_map = {
            p.symbol: abs(int(p.quantity)) for p in positions if p.quantity != 0.0
        }
        entry_credits = compute_entry_credits_for_positions(transactions, position_map)
        for credit in entry_credits.values():
            influx.process_event(credit.for_influx())  # type: ignore[arg-type]
        counts["entry_credits"] = len(entry_credits)
        logger.info("Wrote %d entry credits to InfluxDB", len(entry_credits))

        # --- 4. Backfill positions ---
        logger.info("Backfilling positions...")
        for position in positions:
            influx.process_event(position.for_influx())  # type: ignore[arg-type]
        counts["positions"] = len(positions)
        logger.info("Wrote %d positions to InfluxDB", len(positions))

        # --- Summary ---
        logger.info("Backfill complete: %s", counts)

    finally:
        influx.close()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
