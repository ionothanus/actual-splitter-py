"""Tests for actual_helpers.py"""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from actual_helpers import (
    detect_new_shared_transaction,
    create_deposit_transaction,
    create_transaction_from_spliit,
    find_correlated_split_transaction,
    update_split_transaction,
    CORRELATION_PREFIX,
)


class TestDetectNewSharedTransaction:
    """Tests for detect_new_shared_transaction function."""

    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    @pytest.fixture
    def mock_transaction(self):
        """Create a mock transaction."""
        txn = MagicMock()
        txn.id = "txn-123"
        txn.notes = "Groceries #shared"
        return txn

    @pytest.fixture
    def mock_changeset(self, mock_transaction):
        """Create a mock changeset that returns the transaction."""
        change = MagicMock()
        change.from_orm.return_value = mock_transaction
        return change

    def test_detects_new_shared_tag(self, mock_changeset, mock_transaction, mock_session):
        """Test detecting a newly added #shared tag."""
        existing_transactions: dict[str, str | None] = {}
        changed_columns = {"notes": "Groceries #shared"}

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert result == mock_transaction
        assert existing_transactions["txn-123"] == "Groceries #shared"

    def test_ignores_already_tagged_transaction(self, mock_changeset, mock_transaction, mock_session):
        """Test that already-tagged transactions are ignored on edit."""
        existing_transactions = {"txn-123": "Groceries #shared"}
        changed_columns = {"notes": "Groceries #shared updated"}

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert result is None

    def test_ignores_transaction_without_tag(self, mock_changeset, mock_transaction, mock_session):
        """Test that transactions without the tag are ignored."""
        mock_transaction.notes = "Regular groceries"
        existing_transactions: dict[str, str | None] = {}
        changed_columns = {"notes": "Regular groceries"}

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert result is None

    def test_handles_none_transaction(self, mock_session):
        """Test handling when changeset returns None."""
        change = MagicMock()
        change.from_orm.return_value = None

        result = detect_new_shared_transaction(
            change,
            {},
            mock_session,
            {},
            "#shared",
        )

        assert result is None

    def test_handles_transaction_without_id(self, mock_session):
        """Test handling transaction with no ID."""
        txn = MagicMock()
        txn.id = None
        change = MagicMock()
        change.from_orm.return_value = txn

        result = detect_new_shared_transaction(
            change,
            {},
            mock_session,
            {},
            "#shared",
        )

        assert result is None

    def test_custom_trigger_tag(self, mock_changeset, mock_transaction, mock_session):
        """Test with a custom trigger tag."""
        mock_transaction.notes = "Groceries #split"
        existing_transactions: dict[str, str | None] = {}
        changed_columns = {"notes": "Groceries #split"}

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#split",
        )

        assert result == mock_transaction

    def test_updates_tracking_dict(self, mock_changeset, mock_transaction, mock_session):
        """Test that the tracking dict is updated correctly."""
        existing_transactions: dict[str, str | None] = {}
        changed_columns = {"notes": "New notes #shared"}

        detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert "txn-123" in existing_transactions
        assert existing_transactions["txn-123"] == "New notes #shared"

    def test_edit_existing_transaction_to_add_shared_tag(self, mock_changeset, mock_transaction, mock_session):
        """Test editing an existing transaction to add #shared tag.

        Simulates: Transaction created without #shared, then edited to add it.
        The changeset only contains the notes field when editing.
        """
        mock_transaction.notes = "Test #shared"
        # Transaction existed before with notes "Test" (no tag)
        existing_transactions = {"txn-123": "Test"}
        # Edit changeset only contains the changed field
        changed_columns = {"notes": "Test #shared"}

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert result == mock_transaction
        # Tracking dict should be updated
        assert existing_transactions["txn-123"] == "Test #shared"

    def test_edit_existing_transaction_without_adding_tag(self, mock_changeset, mock_transaction, mock_session):
        """Test editing an existing transaction without adding #shared.

        Simulates: Transaction edited but #shared not added.
        """
        mock_transaction.notes = "Test updated"
        existing_transactions = {"txn-123": "Test"}
        changed_columns = {"notes": "Test updated"}

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert result is None

    def test_edit_amount_on_already_shared_transaction(self, mock_changeset, mock_transaction, mock_session):
        """Test editing amount on a transaction that already has #shared.

        Simulates: Transaction already has #shared, user edits the amount.
        The changeset only contains the amount field.
        """
        mock_transaction.notes = "Test #shared"
        existing_transactions = {"txn-123": "Test #shared"}
        # Amount edit - notes not in changeset
        changed_columns = {"amount": -600}

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        # Should NOT trigger a new split (tag was already present)
        assert result is None
        # Tracking dict should NOT be modified when notes weren't in changeset
        assert existing_transactions["txn-123"] == "Test #shared"

    def test_new_transaction_with_all_fields(self, mock_changeset, mock_transaction, mock_session):
        """Test new transaction with all fields in changeset.

        Simulates: Brand new transaction created with #shared from the start.
        New transactions have all fields in the changeset.
        """
        mock_transaction.notes = "Groceries #shared"
        existing_transactions: dict[str, str | None] = {}
        # New transaction has many fields
        changed_columns = {
            "acct": "account-id",
            "category": "category-id",
            "amount": -500,
            "notes": "Groceries #shared",
            "date": 20260214,
        }

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert result == mock_transaction

    def test_removes_tag_from_transaction(self, mock_changeset, mock_transaction, mock_session):
        """Test removing #shared tag from a transaction.

        This should not trigger anything (tag was already processed).
        """
        mock_transaction.notes = "Test"
        existing_transactions = {"txn-123": "Test #shared"}
        changed_columns = {"notes": "Test"}  # Tag removed

        result = detect_new_shared_transaction(
            mock_changeset,
            changed_columns,
            mock_session,
            existing_transactions,
            "#shared",
        )

        assert result is None
        # Tracking dict should be updated to reflect removed tag
        assert existing_transactions["txn-123"] == "Test"


class TestCreateDepositTransaction:
    """Tests for create_deposit_transaction function."""

    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    @pytest.fixture
    def mock_original_transaction(self):
        """Create a mock original transaction."""
        txn = MagicMock()
        txn.id = "original-txn-123"
        txn.amount = -10000  # -$100.00 (expense)
        txn.date = 20240115  # Actual date format
        txn.get_date.return_value = datetime.date(2024, 1, 15)
        txn.get_amount.return_value = Decimal("-100.00")
        txn.category = MagicMock()
        txn.category.id = "category-123"
        txn.category.name = "Food"
        txn.payee = MagicMock()
        txn.payee.id = "payee-123"
        txn.payee.name = "Grocery Store"
        return txn

    def test_raises_on_no_amount(self, mock_session):
        """Test that ValueError is raised when amount is None."""
        txn = MagicMock()
        txn.amount = None
        txn.date = 20240115

        with pytest.raises(ValueError, match="no amount"):
            create_deposit_transaction(txn, {}, mock_session, "Payee", "Account")

    def test_raises_on_no_date(self, mock_session):
        """Test that ValueError is raised when date is None."""
        txn = MagicMock()
        txn.amount = -10000
        txn.date = None

        with pytest.raises(ValueError, match="no date"):
            create_deposit_transaction(txn, {}, mock_session, "Payee", "Account")

    def test_raises_on_no_id(self, mock_session):
        """Test that ValueError is raised when ID is None."""
        txn = MagicMock()
        txn.amount = -10000
        txn.date = 20240115
        txn.id = None

        with pytest.raises(ValueError, match="no ID"):
            create_deposit_transaction(txn, {}, mock_session, "Payee", "Account")

    @patch("actual_helpers.get_payee")
    def test_raises_on_missing_payee(self, mock_get_payee, mock_session, mock_original_transaction):
        """Test that ValueError is raised when payee not found."""
        mock_get_payee.return_value = None

        with pytest.raises(ValueError, match="Payee 'Unknown' not found"):
            create_deposit_transaction(
                mock_original_transaction, {}, mock_session, "Unknown", "Account"
            )

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    def test_raises_on_missing_account(
        self, mock_get_account, mock_get_payee, mock_session, mock_original_transaction
    ):
        """Test that ValueError is raised when account not found."""
        mock_get_payee.return_value = MagicMock()
        mock_get_account.return_value = None

        with pytest.raises(ValueError, match="Account 'Unknown' not found"):
            create_deposit_transaction(
                mock_original_transaction, {}, mock_session, "Payee", "Unknown"
            )

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction_from_ids")
    def test_creates_transaction_with_half_amount(
        self,
        mock_create_txn,
        mock_get_account,
        mock_get_payee,
        mock_session,
        mock_original_transaction,
    ):
        """Test that deposit is created for half the original amount."""
        mock_payee = MagicMock()
        mock_payee.id = "payee-id-123"
        mock_account = MagicMock()
        mock_account.id = "account-id-123"
        mock_get_payee.return_value = mock_payee
        mock_get_account.return_value = mock_account
        mock_deposit = MagicMock()
        mock_create_txn.return_value = mock_deposit

        result = create_deposit_transaction(
            mock_original_transaction, {}, mock_session, "Payee", "Account"
        )

        mock_create_txn.assert_called_once()
        call_kwargs = mock_create_txn.call_args[1]

        # Amount should be half (positive, since it's a deposit for shared expense)
        # Original is -100.00, half is -50.00, negated to 50.00
        assert call_kwargs["amount"] == Decimal("50.00")
        assert call_kwargs["payee_id"] == "payee-id-123"
        assert call_kwargs["account_id"] == "account-id-123"
        assert "#auto" in call_kwargs["notes"]
        assert "Grocery Store" in call_kwargs["notes"]
        # Verify correlation reference is set
        assert mock_deposit.imported_description == "ref:original-txn-123"
        assert result == mock_deposit

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction_from_ids")
    def test_uses_changed_amount(
        self,
        mock_create_txn,
        mock_get_account,
        mock_get_payee,
        mock_session,
        mock_original_transaction,
    ):
        """Test that changed amount from changeset is used."""
        mock_payee = MagicMock()
        mock_payee.id = "payee-id"
        mock_account = MagicMock()
        mock_account.id = "account-id"
        mock_get_payee.return_value = mock_payee
        mock_get_account.return_value = mock_account
        mock_create_txn.return_value = MagicMock()

        change = {"amount": -20000}  # Changed to -$200.00

        create_deposit_transaction(
            mock_original_transaction, change, mock_session, "Payee", "Account"
        )

        call_kwargs = mock_create_txn.call_args[1]
        # Half of $200.00 = $100.00
        assert call_kwargs["amount"] == Decimal("100.00")

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction_from_ids")
    def test_custom_auto_tag(
        self,
        mock_create_txn,
        mock_get_account,
        mock_get_payee,
        mock_session,
        mock_original_transaction,
    ):
        """Test using a custom auto tag."""
        mock_payee = MagicMock()
        mock_payee.id = "payee-id"
        mock_account = MagicMock()
        mock_account.id = "account-id"
        mock_get_payee.return_value = mock_payee
        mock_get_account.return_value = mock_account
        mock_create_txn.return_value = MagicMock()

        create_deposit_transaction(
            mock_original_transaction,
            {},
            mock_session,
            "Payee",
            "Account",
            auto_tag="#custom",
        )

        call_kwargs = mock_create_txn.call_args[1]
        assert "#custom" in call_kwargs["notes"]


class TestCreateTransactionFromSpliit:
    """Tests for create_transaction_from_spliit function."""

    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    @patch("actual_helpers.get_payee")
    def test_raises_on_missing_payee(self, mock_get_payee, mock_session):
        """Test that ValueError is raised when payee not found."""
        mock_get_payee.return_value = None

        with pytest.raises(ValueError, match="Payee 'Unknown' not found"):
            create_transaction_from_spliit(
                mock_session,
                "Unknown",
                "Account",
                datetime.date(2024, 1, 15),
                5000,
                None,
                "Dinner",
                "Alice",
            )

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    def test_raises_on_missing_account(self, mock_get_account, mock_get_payee, mock_session):
        """Test that ValueError is raised when account not found."""
        mock_get_payee.return_value = MagicMock()
        mock_get_account.return_value = None

        with pytest.raises(ValueError, match="Account 'Unknown' not found"):
            create_transaction_from_spliit(
                mock_session,
                "Payee",
                "Unknown",
                datetime.date(2024, 1, 15),
                5000,
                None,
                "Dinner",
                "Alice",
            )

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction")
    def test_creates_transaction_with_correct_amount(
        self, mock_create_txn, mock_get_account, mock_get_payee, mock_session
    ):
        """Test that transaction is created with correct negative amount."""
        mock_payee = MagicMock()
        mock_account = MagicMock()
        mock_get_payee.return_value = mock_payee
        mock_get_account.return_value = mock_account

        create_transaction_from_spliit(
            mock_session,
            "Payee",
            "Account",
            datetime.date(2024, 1, 15),
            5000,  # $50.00
            None,
            "Dinner",
            "Alice",
        )

        mock_create_txn.assert_called_once()
        call_kwargs = mock_create_txn.call_args[1]

        # Amount should be negative (expense)
        assert call_kwargs["amount"] == Decimal("-50.00")
        assert call_kwargs["date"] == datetime.date(2024, 1, 15)

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction")
    def test_notes_format(
        self, mock_create_txn, mock_get_account, mock_get_payee, mock_session
    ):
        """Test that notes are formatted correctly."""
        mock_get_payee.return_value = MagicMock()
        mock_get_account.return_value = MagicMock()

        create_transaction_from_spliit(
            mock_session,
            "Payee",
            "Account",
            datetime.date(2024, 1, 15),
            5000,
            None,
            "Dinner at Restaurant",
            "Alice",
        )

        call_kwargs = mock_create_txn.call_args[1]
        assert call_kwargs["notes"] == "Dinner at Restaurant (paid by Alice) #spliit"

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction")
    def test_custom_tag(
        self, mock_create_txn, mock_get_account, mock_get_payee, mock_session
    ):
        """Test using a custom tag."""
        mock_get_payee.return_value = MagicMock()
        mock_get_account.return_value = MagicMock()

        create_transaction_from_spliit(
            mock_session,
            "Payee",
            "Account",
            datetime.date(2024, 1, 15),
            5000,
            None,
            "Dinner",
            "Alice",
            tag="#custom",
        )

        call_kwargs = mock_create_txn.call_args[1]
        assert "#custom" in call_kwargs["notes"]

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction")
    def test_with_category(
        self, mock_create_txn, mock_get_account, mock_get_payee, mock_session
    ):
        """Test that category is passed through."""
        mock_get_payee.return_value = MagicMock()
        mock_get_account.return_value = MagicMock()
        mock_category = MagicMock()

        create_transaction_from_spliit(
            mock_session,
            "Payee",
            "Account",
            datetime.date(2024, 1, 15),
            5000,
            mock_category,
            "Dinner",
            "Alice",
        )

        call_kwargs = mock_create_txn.call_args[1]
        assert call_kwargs["category"] == mock_category


class TestFindCorrelatedSplitTransaction:
    """Tests for find_correlated_split_transaction function."""

    def test_finds_correlated_transaction(self):
        """Test finding a correlated split transaction by imported_description."""
        mock_session = MagicMock()
        mock_split_txn = MagicMock()
        mock_session.exec.return_value.first.return_value = mock_split_txn

        result = find_correlated_split_transaction(mock_session, "original-123")

        assert result == mock_split_txn
        # Verify the query was constructed correctly
        mock_session.exec.assert_called_once()

    def test_returns_none_when_not_found(self):
        """Test that None is returned when no correlated transaction exists."""
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None

        result = find_correlated_split_transaction(mock_session, "nonexistent-123")

        assert result is None

    def test_correlation_prefix_format(self):
        """Test that CORRELATION_PREFIX is correctly defined."""
        assert CORRELATION_PREFIX == "ref:"


class TestUpdateSplitTransaction:
    """Tests for update_split_transaction function."""

    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    @pytest.fixture
    def mock_split_transaction(self):
        """Create a mock split transaction that is not cleared/reconciled."""
        txn = MagicMock()
        txn.id = "split-123"
        txn.cleared = False
        txn.reconciled = False
        return txn

    def test_skips_cleared_transaction(self, mock_session):
        """Test that cleared transactions are not updated."""
        txn = MagicMock()
        txn.cleared = True
        txn.reconciled = False

        result = update_split_transaction(mock_session, txn, new_amount_cents=-20000)

        assert result is False
        txn.set_amount.assert_not_called()

    def test_skips_reconciled_transaction(self, mock_session):
        """Test that reconciled transactions are not updated."""
        txn = MagicMock()
        txn.cleared = False
        txn.reconciled = True

        result = update_split_transaction(mock_session, txn, new_amount_cents=-20000)

        assert result is False
        txn.set_amount.assert_not_called()

    def test_updates_amount(self, mock_session, mock_split_transaction):
        """Test updating the split transaction amount."""
        result = update_split_transaction(
            mock_session, mock_split_transaction, new_amount_cents=-20000
        )

        assert result is True
        # Amount should be halved and negated: -20000 cents -> 10000 cents = $100.00 / 2 = $50.00
        mock_split_transaction.set_amount.assert_called_once_with(Decimal("100.00"))
        mock_session.flush.assert_called_once()

    def test_updates_date(self, mock_session, mock_split_transaction):
        """Test updating the split transaction date."""
        result = update_split_transaction(
            mock_session, mock_split_transaction, new_date=20240220
        )

        assert result is True
        mock_split_transaction.set_date.assert_called_once_with(datetime.date(2024, 2, 20))
        mock_session.flush.assert_called_once()

    def test_updates_category(self, mock_session, mock_split_transaction):
        """Test updating the split transaction category."""
        result = update_split_transaction(
            mock_session, mock_split_transaction, new_category_id="new-category-123"
        )

        assert result is True
        assert mock_split_transaction.category_id == "new-category-123"
        mock_session.flush.assert_called_once()

    def test_updates_multiple_fields(self, mock_session, mock_split_transaction):
        """Test updating multiple fields at once."""
        result = update_split_transaction(
            mock_session,
            mock_split_transaction,
            new_amount_cents=-30000,
            new_date=20240315,
            new_category_id="category-456",
        )

        assert result is True
        mock_split_transaction.set_amount.assert_called_once()
        mock_split_transaction.set_date.assert_called_once()
        assert mock_split_transaction.category_id == "category-456"
        mock_session.flush.assert_called_once()

    def test_no_update_when_no_changes(self, mock_session, mock_split_transaction):
        """Test that flush is not called when no changes are made."""
        result = update_split_transaction(mock_session, mock_split_transaction)

        assert result is False
        mock_session.flush.assert_not_called()
