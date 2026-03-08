"""Unit tests for transaction LIFO entry credit computation."""

from datetime import datetime, timezone
from decimal import Decimal

from tastytrade.accounts.transactions import (
    Transaction,
    compute_entry_credit_lifo,
    compute_entry_credits_for_positions,
)


def make_txn(
    txn_id: int,
    action: str,
    symbol: str,
    quantity: int,
    value: Decimal,
    value_effect: str,
    executed_at: datetime | None = None,
    underlying: str = "SPY",
    price: Decimal = Decimal("1.00"),
    net_value: Decimal | None = None,
) -> Transaction:
    """Create a Transaction for testing."""
    if executed_at is None:
        executed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    if net_value is None:
        net_value = value
    return Transaction.model_validate(
        {
            "id": txn_id,
            "executed-at": executed_at.isoformat(),
            "action": action,
            "symbol": symbol,
            "underlying-symbol": underlying,
            "instrument-type": "Equity Option",
            "price": price,
            "value": value,
            "value-effect": value_effect,
            "net-value": net_value,
            "net-value-effect": value_effect,
            "quantity": Decimal(str(quantity)),
            "order-id": 1000 + txn_id,
            "leg-count": 1,
        }
    )


class TestComputeEntryCreditLifo:
    """Test LIFO reverse replay algorithm."""

    def test_single_open_credit(self) -> None:
        """Single sell-to-open → full credit."""
        txns = [
            make_txn(
                1,
                "Sell to Open",
                "SPY 250P",
                2,
                Decimal("300.00"),
                "Credit",
                price=Decimal("1.50"),
            ),
        ]
        result = compute_entry_credit_lifo(txns, 2)
        assert result is not None
        assert result.entry_credit == Decimal("300.00")
        assert result.weighted_price == Decimal("1.50")

    def test_single_open_debit(self) -> None:
        """Single buy-to-open → negative (debit)."""
        txns = [
            make_txn(
                1,
                "Buy to Open",
                "SPY 260C",
                3,
                Decimal("450.00"),
                "Debit",
                price=Decimal("1.50"),
            ),
        ]
        result = compute_entry_credit_lifo(txns, 3)
        assert result is not None
        assert result.entry_credit == Decimal("-450.00")
        assert result.weighted_price == Decimal("1.50")

    def test_partial_close_lifo(self) -> None:
        """Open 5, close 2 → LIFO keeps last 3 from the open fill."""
        txns = [
            make_txn(
                1,
                "Sell to Open",
                "SPY 250P",
                5,
                Decimal("500.00"),
                "Credit",
                datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            make_txn(
                2,
                "Buy to Close",
                "SPY 250P",
                2,
                Decimal("180.00"),
                "Debit",
                datetime(2025, 1, 5, tzinfo=timezone.utc),
            ),
        ]
        result = compute_entry_credit_lifo(txns, 3)
        assert result is not None
        # Open 5 for $500, close 2 → 3 surviving, proportional = 500 * 3/5 = 300
        assert result.entry_credit == Decimal("300.00")

    def test_multiple_opens_lifo_order(self) -> None:
        """Two opens, close 1 → LIFO consumes from most recent open first."""
        txns = [
            make_txn(
                1,
                "Sell to Open",
                "SPY 250P",
                2,
                Decimal("200.00"),
                "Credit",
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                price=Decimal("1.00"),
            ),
            make_txn(
                2,
                "Sell to Open",
                "SPY 250P",
                3,
                Decimal("360.00"),
                "Credit",
                datetime(2025, 1, 10, tzinfo=timezone.utc),
                price=Decimal("1.20"),
            ),
            make_txn(
                3,
                "Buy to Close",
                "SPY 250P",
                1,
                Decimal("100.00"),
                "Debit",
                datetime(2025, 1, 15, tzinfo=timezone.utc),
            ),
        ]
        result = compute_entry_credit_lifo(txns, 4)
        assert result is not None
        # Newest-to-oldest: close(1), open(3@1.20), open(2@1.00)
        # Close buffer=1, open(3): consumed=1, surviving=2, take=2 → 360*2/3=240
        # open(2): consumed=0, surviving=2, take=2 → 200
        # Total = 440
        assert result.entry_credit == Decimal("440.00")
        # Weighted price: (1.20*2 + 1.00*2) / 4 = 4.40/4 = 1.10
        assert result.weighted_price == Decimal("1.10")

    def test_zero_quantity_returns_zero(self) -> None:
        result = compute_entry_credit_lifo([], 0)
        assert result is not None
        assert result.entry_credit == Decimal("0")

    def test_incomplete_replay_returns_none(self) -> None:
        """Not enough opens to account for current qty → None."""
        txns = [
            make_txn(1, "Sell to Open", "SPY 250P", 1, Decimal("100.00"), "Credit"),
        ]
        result = compute_entry_credit_lifo(txns, 5)
        assert result is None

    def test_full_rollover(self) -> None:
        """Open 2, close 2, re-open 2 → only the re-open contributes."""
        txns = [
            make_txn(
                1,
                "Sell to Open",
                "SPY 250P",
                2,
                Decimal("200.00"),
                "Credit",
                datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            make_txn(
                2,
                "Buy to Close",
                "SPY 250P",
                2,
                Decimal("150.00"),
                "Debit",
                datetime(2025, 1, 5, tzinfo=timezone.utc),
            ),
            make_txn(
                3,
                "Sell to Open",
                "SPY 250P",
                2,
                Decimal("250.00"),
                "Credit",
                datetime(2025, 1, 10, tzinfo=timezone.utc),
            ),
        ]
        result = compute_entry_credit_lifo(txns, 2)
        assert result is not None
        assert result.entry_credit == Decimal("250.00")

    def test_fees_accumulated(self) -> None:
        """Fees are computed from value vs net_value difference."""
        txns = [
            make_txn(
                1,
                "Sell to Open",
                "SPY 250P",
                2,
                Decimal("300.00"),
                "Credit",
                net_value=Decimal("299.80"),  # 0.20 in fees
            ),
        ]
        result = compute_entry_credit_lifo(txns, 2)
        assert result is not None
        assert result.fees == Decimal("0.20")

    def test_fees_proportional(self) -> None:
        """Fees are proportional when only part of a fill is used."""
        txns = [
            make_txn(
                1,
                "Sell to Open",
                "SPY 250P",
                4,
                Decimal("400.00"),
                "Credit",
                net_value=Decimal("399.60"),  # 0.40 total fees
            ),
        ]
        result = compute_entry_credit_lifo(txns, 2)
        assert result is not None
        # Only 2 of 4 contracts used → fees = 0.40 * 2/4 = 0.20
        assert result.fees == Decimal("0.20")


class TestComputeEntryCreditsForPositions:
    """Test batch entry credit computation."""

    def test_multiple_symbols(self) -> None:
        txns = [
            make_txn(
                1,
                "Sell to Open",
                "SPY 250P",
                1,
                Decimal("100"),
                "Credit",
                price=Decimal("1.00"),
            ),
            make_txn(
                2,
                "Buy to Open",
                "SPY 260C",
                1,
                Decimal("200"),
                "Debit",
                price=Decimal("2.00"),
            ),
        ]
        positions = {
            "SPY 250P": 1,
            "SPY 260C": 1,
        }
        results = compute_entry_credits_for_positions(txns, positions)
        assert "SPY 250P" in results
        assert results["SPY 250P"].value == Decimal("100")
        assert results["SPY 250P"].per_unit_price == Decimal("1.00")
        assert "SPY 260C" in results
        assert results["SPY 260C"].value == Decimal("-200")
        assert results["SPY 260C"].per_unit_price == Decimal("2.00")

    def test_missing_transactions_skipped(self) -> None:
        """Positions with no matching transactions are omitted."""
        positions = {"AAPL 150C": 1}
        results = compute_entry_credits_for_positions([], positions)
        assert len(results) == 0

    def test_incomplete_lifo_excluded(self) -> None:
        """If LIFO can't account for full qty, symbol is excluded."""
        txns = [
            make_txn(1, "Sell to Open", "SPY 250P", 1, Decimal("50"), "Credit"),
        ]
        positions = {"SPY 250P": 10}
        results = compute_entry_credits_for_positions(txns, positions)
        assert "SPY 250P" not in results


class TestTransactionModel:
    """Test Transaction Pydantic model."""

    def test_parse_api_response(self) -> None:
        raw = {
            "id": 42,
            "executed-at": "2025-03-01T14:30:00+00:00",
            "action": "Sell to Open",
            "symbol": "SPY   250321P00500000",
            "underlying-symbol": "SPY",
            "instrument-type": "Equity Option",
            "price": "1.50",
            "value": "150.00",
            "value-effect": "Credit",
            "net-value": "148.70",
            "net-value-effect": "Credit",
            "quantity": "1",
            "order-id": 9999,
            "leg-count": 2,
        }
        txn = Transaction.model_validate(raw)
        assert txn.id == 42
        assert txn.action == "Sell to Open"
        assert txn.value == Decimal("150.00")
        assert txn.value_effect == "Credit"
        assert txn.quantity == Decimal("1")
        assert txn.leg_count == 2

    def test_extra_fields_allowed(self) -> None:
        """Brokerage may send extra fields — model must not reject them."""
        raw = {
            "id": 1,
            "executed-at": "2025-01-01T00:00:00+00:00",
            "action": "Buy to Open",
            "symbol": "AAPL 150C",
            "underlying-symbol": "AAPL",
            "instrument-type": "Equity Option",
            "price": "2.00",
            "value": "200.00",
            "value-effect": "Debit",
            "net-value": "201.30",
            "net-value-effect": "Debit",
            "quantity": "1",
            "order-id": 100,
            "leg-count": 1,
            "some-future-field": "surprise",
        }
        txn = Transaction.model_validate(raw)
        assert txn.id == 1
