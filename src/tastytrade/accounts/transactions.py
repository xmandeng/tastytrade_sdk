"""Transaction history client and LIFO entry credit computation.

Fetches trade fills from GET /accounts/{acct}/transactions and computes
dollar-valued entry credits via reverse (LIFO) replay. Used for all option
types — the API returns identical ``value`` (dollar) fields for both equity
and futures options.

**API quirk — mixed transaction types in response:**
The Transactions API may return non-Trade items (e.g. "Money Movement" /
"Balance Adjustment" for regulatory fee adjustments) even when the request
explicitly filters by ``transaction-type=Trade``. These items have a
different schema (no ``action``, ``symbol``, ``quantity``, etc.) and must
be filtered out before parsing. The ``TransactionsClient`` handles this
automatically via a ``transaction-type`` check on each item.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field

from tastytrade.accounts.models import InfluxMixin

from tastytrade.connections.requests import AsyncSessionHandler
from tastytrade.utils.validators import validate_async_response

logger = logging.getLogger(__name__)


class Transaction(BaseModel):
    """A single trade fill from the Transactions API."""

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    id: int
    executed_at: datetime = Field(alias="executed-at")
    action: str = Field(alias="action")
    symbol: str = Field(alias="symbol")
    underlying_symbol: str = Field(alias="underlying-symbol")
    instrument_type: str = Field(alias="instrument-type")
    price: Decimal = Field(alias="price")
    value: Decimal = Field(alias="value")
    value_effect: str = Field(alias="value-effect")
    net_value: Decimal = Field(alias="net-value")
    net_value_effect: str = Field(alias="net-value-effect")
    quantity: Decimal = Field(alias="quantity")
    order_id: int = Field(alias="order-id")
    leg_count: Optional[int] = Field(default=None, alias="leg-count")


class EntryCredit(BaseModel, InfluxMixin):
    """Computed entry credit for a single position, stored in Redis."""

    model_config = ConfigDict(populate_by_name=True)
    INFLUX_JSON_FIELDS: ClassVar[set[str]] = set()
    INFLUX_EXCLUDE: ClassVar[set[str]] = set()
    INFLUX_TIME_FIELD: ClassVar[str] = "computed_at"

    symbol: str
    value: Decimal
    fees: Decimal = Decimal("0")
    per_unit_price: Optional[Decimal] = None
    method: str = "transaction_lifo"
    transaction_count: int
    computed_at: Optional[datetime] = None

    @property
    def eventSymbol(self) -> str:
        return self.symbol


class TransactionsClient:
    """Fetches transaction history from the TastyTrade REST API."""

    def __init__(self, session: AsyncSessionHandler) -> None:
        self.session = session

    async def get_transactions(
        self,
        account_number: str,
        instrument_type: Optional[str] = None,
        per_page: int = 250,
    ) -> list[Transaction]:
        """Fetch trade transactions for an account.

        Note: The API may return non-Trade items (fee adjustments, balance
        adjustments) even with ``transaction-type=Trade`` filter. These are
        filtered out automatically before parsing.

        Args:
            account_number: The account to query.
            instrument_type: Optional filter (e.g., "Equity Option", "Future Option").
            per_page: Page size for pagination.

        Returns:
            All matching Trade transactions across all pages, newest first.
        """
        all_transactions: list[Transaction] = []
        page_offset = 0

        while True:
            params: dict[str, str | int] = {
                "per-page": per_page,
                "page-offset": page_offset,
                "sort": "Desc",
                "transaction-type": "Trade",
            }
            if instrument_type:
                params["instrument-type"] = instrument_type

            async with self.session.session.get(
                f"{self.session.base_url}/accounts/{account_number}/transactions",
                params=params,
            ) as response:
                await validate_async_response(response)
                data = await response.json()

            items = data["data"]["items"]
            for item in items:
                # The API may include non-trade items (e.g. fee adjustments)
                # even when filtering by transaction-type=Trade. Skip them.
                if item.get("transaction-type") != "Trade":
                    continue
                all_transactions.append(Transaction.model_validate(item))

            pagination = data.get("pagination", {})
            total_pages = pagination.get("total-pages", 1)
            page_offset += 1

            if page_offset >= total_pages:
                break

        logger.info("Fetched %d transactions", len(all_transactions))
        return all_transactions


OPEN_ACTIONS = {"Sell to Open", "Buy to Open"}
CLOSE_ACTIONS = {"Buy to Close", "Sell to Close"}


@dataclass(frozen=True)
class LifoResult:
    """Result of a LIFO reverse replay for a single symbol."""

    entry_credit: Decimal
    fees: Decimal
    weighted_price: Optional[Decimal]


def compute_entry_credit_lifo(
    transactions: list[Transaction],
    current_qty: int,
) -> Optional[LifoResult]:
    """Walk transactions newest-to-oldest, reconstruct entry credit via LIFO.

    The LIFO replay identifies which specific fills constitute the current
    position. The position-level rollup (dollar entry credit) is derived
    from those identified fills.

    Args:
        transactions: All transactions for a single symbol, any order.
        current_qty: Absolute quantity of the current position.

    Returns:
        LifoResult with entry credit, fees, and weighted average price,
        or None if transactions don't fully account for the position.
    """
    if current_qty == 0:
        return LifoResult(Decimal("0"), Decimal("0"), None)

    txns = sorted(transactions, key=lambda t: t.executed_at, reverse=True)

    remaining = abs(current_qty)
    close_buffer = 0
    entry_credit = Decimal("0")
    total_fees = Decimal("0")
    price_x_qty = Decimal("0")
    total_qty = Decimal("0")

    for txn in txns:
        if remaining == 0:
            break

        qty = int(txn.quantity)

        if txn.action in CLOSE_ACTIONS:
            close_buffer += qty
            continue

        if txn.action in OPEN_ACTIONS:
            consumed = min(qty, close_buffer)
            close_buffer -= consumed
            surviving = qty - consumed

            take = min(surviving, remaining)
            if take > 0:
                fraction = Decimal(take) / Decimal(qty)
                proportional_value = txn.value * fraction
                sign = Decimal("1") if txn.value_effect == "Credit" else Decimal("-1")
                entry_credit += proportional_value * sign

                # Accumulate fees: difference between value and net_value
                proportional_fees = abs(txn.net_value - txn.value) * fraction
                total_fees += proportional_fees

                # Weighted average price (per-unit)
                price_x_qty += txn.price * take
                total_qty += take

                remaining -= take

    if remaining != 0:
        logger.warning(
            "LIFO replay incomplete: %d contracts unaccounted for", remaining
        )
        return None

    weighted_price = (price_x_qty / total_qty) if total_qty > 0 else None

    return LifoResult(
        entry_credit=entry_credit,
        fees=total_fees,
        weighted_price=weighted_price,
    )


def compute_entry_credits_for_positions(
    transactions: list[Transaction],
    positions: dict[str, int],
) -> dict[str, EntryCredit]:
    """Compute entry credits for multiple positions from transaction history.

    Args:
        transactions: All option transactions for the account.
        positions: Map of symbol → abs_quantity.

    Returns:
        Map of symbol → EntryCredit for positions where computation succeeded.
    """
    by_symbol: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        by_symbol[txn.symbol].append(txn)

    results: dict[str, EntryCredit] = {}

    for symbol, qty in positions.items():
        symbol_txns = by_symbol.get(symbol, [])
        if not symbol_txns:
            continue

        result = compute_entry_credit_lifo(symbol_txns, qty)
        if result is not None:
            results[symbol] = EntryCredit(
                symbol=symbol,
                value=result.entry_credit,
                fees=result.fees,
                per_unit_price=result.weighted_price,
                transaction_count=len(symbol_txns),
                computed_at=datetime.now(timezone.utc),
            )

    logger.info(
        "Computed entry credits for %d of %d positions",
        len(results),
        len(positions),
    )
    return results
