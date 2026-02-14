"""Tests for actual_helpers.py"""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from actual_helpers import (
    detect_new_shared_transaction,
    create_deposit_transaction,
    create_transaction_from_spliit,
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


class TestCreateDepositTransaction:
    """Tests for create_deposit_transaction function."""

    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    @pytest.fixture
    def mock_original_transaction(self):
        """Create a mock original transaction."""
        txn = MagicMock()
        txn.amount = -10000  # -$100.00 (expense)
        txn.date = 20240115  # Actual date format
        txn.get_date.return_value = datetime.date(2024, 1, 15)
        txn.get_amount.return_value = Decimal("-100.00")
        txn.category = MagicMock()
        txn.category.name = "Food"
        txn.payee = MagicMock()
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
    @patch("actual_helpers.create_transaction")
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
        mock_account = MagicMock()
        mock_get_payee.return_value = mock_payee
        mock_get_account.return_value = mock_account

        create_deposit_transaction(
            mock_original_transaction, {}, mock_session, "Payee", "Account"
        )

        mock_create_txn.assert_called_once()
        call_kwargs = mock_create_txn.call_args[1]

        # Amount should be half (positive, since it's a deposit for shared expense)
        # Original is -100.00, half is -50.00, negated to 50.00
        assert call_kwargs["amount"] == Decimal("50.00")
        assert call_kwargs["payee"] == mock_payee
        assert call_kwargs["account"] == mock_account
        assert "#auto" in call_kwargs["notes"]
        assert "Grocery Store" in call_kwargs["notes"]

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction")
    def test_uses_changed_amount(
        self,
        mock_create_txn,
        mock_get_account,
        mock_get_payee,
        mock_session,
        mock_original_transaction,
    ):
        """Test that changed amount from changeset is used."""
        mock_get_payee.return_value = MagicMock()
        mock_get_account.return_value = MagicMock()

        change = {"amount": -20000}  # Changed to -$200.00

        create_deposit_transaction(
            mock_original_transaction, change, mock_session, "Payee", "Account"
        )

        call_kwargs = mock_create_txn.call_args[1]
        # Half of $200.00 = $100.00
        assert call_kwargs["amount"] == Decimal("100.00")

    @patch("actual_helpers.get_payee")
    @patch("actual_helpers.get_account")
    @patch("actual_helpers.create_transaction")
    def test_custom_auto_tag(
        self,
        mock_create_txn,
        mock_get_account,
        mock_get_payee,
        mock_session,
        mock_original_transaction,
    ):
        """Test using a custom auto tag."""
        mock_get_payee.return_value = MagicMock()
        mock_get_account.return_value = MagicMock()

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
