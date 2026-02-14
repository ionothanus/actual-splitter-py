"""Tests for spliit_helpers.py"""

import datetime
import pytest
from unittest.mock import MagicMock, patch

from spliit_helpers import (
    calculate_my_share,
    create_spliit_expense,
    update_spliit_expense,
    delete_spliit_expense,
)


class TestCalculateMyShare:
    """Tests for the calculate_my_share function."""

    @pytest.fixture
    def my_participant_id(self):
        return "participant-123"

    @pytest.fixture
    def other_participant_id(self):
        return "participant-456"

    def test_even_split_two_people(self, my_participant_id, other_participant_id):
        """Test even split between two people."""
        expense = {
            "amount": 10000,  # $100.00
            "splitMode": "EVENLY",
            "paidFor": [
                {"participant": {"id": my_participant_id}},
                {"participant": {"id": other_participant_id}},
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 5000

    def test_even_split_three_people(self, my_participant_id):
        """Test even split between three people."""
        expense = {
            "amount": 9000,  # $90.00
            "splitMode": "EVENLY",
            "paidFor": [
                {"participant": {"id": my_participant_id}},
                {"participant": {"id": "participant-2"}},
                {"participant": {"id": "participant-3"}},
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 3000

    def test_not_in_expense(self, my_participant_id, other_participant_id):
        """Test when I'm not part of the expense."""
        expense = {
            "amount": 10000,
            "splitMode": "EVENLY",
            "paidFor": [
                {"participant": {"id": other_participant_id}},
                {"participant": {"id": "participant-3"}},
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 0

    def test_by_shares(self, my_participant_id, other_participant_id):
        """Test split by shares (e.g., 2:1 ratio)."""
        expense = {
            "amount": 9000,  # $90.00
            "splitMode": "BY_SHARES",
            "paidFor": [
                {"participant": {"id": my_participant_id}, "shares": 200},  # 2 shares
                {"participant": {"id": other_participant_id}, "shares": 100},  # 1 share
            ],
        }
        # My share: 9000 * 200 / 300 = 6000
        assert calculate_my_share(expense, my_participant_id) == 6000

    def test_by_shares_equal(self, my_participant_id, other_participant_id):
        """Test split by shares with equal shares."""
        expense = {
            "amount": 10000,
            "splitMode": "BY_SHARES",
            "paidFor": [
                {"participant": {"id": my_participant_id}, "shares": 100},
                {"participant": {"id": other_participant_id}, "shares": 100},
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 5000

    def test_by_percentage(self, my_participant_id, other_participant_id):
        """Test split by percentage."""
        expense = {
            "amount": 10000,
            "splitMode": "BY_PERCENTAGE",
            "paidFor": [
                {"participant": {"id": my_participant_id}, "shares": 3000},  # 30%
                {"participant": {"id": other_participant_id}, "shares": 7000},  # 70%
            ],
        }
        # My share: 10000 * 3000 / 10000 = 3000
        assert calculate_my_share(expense, my_participant_id) == 3000

    def test_by_percentage_half(self, my_participant_id, other_participant_id):
        """Test split by percentage at 50%."""
        expense = {
            "amount": 10000,
            "splitMode": "BY_PERCENTAGE",
            "paidFor": [
                {"participant": {"id": my_participant_id}, "shares": 5000},  # 50%
                {"participant": {"id": other_participant_id}, "shares": 5000},  # 50%
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 5000

    def test_by_amount(self, my_participant_id, other_participant_id):
        """Test split by fixed amount."""
        expense = {
            "amount": 10000,
            "splitMode": "BY_AMOUNT",
            "paidFor": [
                {"participant": {"id": my_participant_id}, "shares": 3500},
                {"participant": {"id": other_participant_id}, "shares": 6500},
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 3500

    def test_unknown_split_mode_defaults_to_even(self, my_participant_id, other_participant_id):
        """Test that unknown split mode falls back to even split."""
        expense = {
            "amount": 10000,
            "splitMode": "UNKNOWN_MODE",
            "paidFor": [
                {"participant": {"id": my_participant_id}},
                {"participant": {"id": other_participant_id}},
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 5000

    def test_default_split_mode_is_even(self, my_participant_id, other_participant_id):
        """Test that missing splitMode defaults to EVENLY."""
        expense = {
            "amount": 10000,
            "paidFor": [
                {"participant": {"id": my_participant_id}},
                {"participant": {"id": other_participant_id}},
            ],
        }
        assert calculate_my_share(expense, my_participant_id) == 5000

    def test_integer_division_rounds_down(self, my_participant_id):
        """Test that integer division rounds down."""
        expense = {
            "amount": 10000,
            "splitMode": "EVENLY",
            "paidFor": [
                {"participant": {"id": my_participant_id}},
                {"participant": {"id": "participant-2"}},
                {"participant": {"id": "participant-3"}},
            ],
        }
        # 10000 / 3 = 3333.33... -> 3333
        assert calculate_my_share(expense, my_participant_id) == 3333


class TestCreateSpliitExpense:
    """Tests for the create_spliit_expense function."""

    @pytest.fixture
    def mock_transaction(self):
        """Create a mock Actual transaction."""
        txn = MagicMock()
        txn.amount = -5000  # -$50.00
        txn.date = 20240115
        txn.id = "txn-123"
        txn.payee = MagicMock()
        txn.payee.name = "Test Store"
        txn.category = MagicMock()
        txn.category.name = "Groceries"
        txn.get_date.return_value = datetime.date(2024, 1, 15)
        return txn

    @pytest.fixture
    def mock_spliit_client(self):
        """Create a mock Spliit client."""
        client = MagicMock()
        client.create_expense.return_value = {"expenseId": "spliit-expense-456"}
        return client

    def test_returns_expense_id(self, mock_transaction, mock_spliit_client):
        """Test that create_spliit_expense returns the expense ID."""
        session = MagicMock()

        with patch("spliit_helpers.map_actual_to_spliit_category", return_value=1):
            result = create_spliit_expense(
                mock_transaction, {}, mock_spliit_client, session, {}
            )

        assert result == "spliit-expense-456"

    def test_returns_none_when_no_expense_id(self, mock_transaction, mock_spliit_client):
        """Test that None is returned when no expense ID in response."""
        mock_spliit_client.create_expense.return_value = {}
        session = MagicMock()

        with patch("spliit_helpers.map_actual_to_spliit_category", return_value=1):
            result = create_spliit_expense(
                mock_transaction, {}, mock_spliit_client, session, {}
            )

        assert result is None

    def test_uses_payee_name_as_title(self, mock_transaction, mock_spliit_client):
        """Test that the payee name is used as the expense title."""
        session = MagicMock()

        with patch("spliit_helpers.map_actual_to_spliit_category", return_value=0):
            create_spliit_expense(
                mock_transaction, {}, mock_spliit_client, session, {}
            )

        mock_spliit_client.create_expense.assert_called_once()
        call_kwargs = mock_spliit_client.create_expense.call_args[1]
        assert call_kwargs["title"] == "Test Store"


class TestUpdateSpliitExpense:
    """Tests for the update_spliit_expense function."""

    @pytest.fixture
    def mock_spliit_client(self):
        """Create a mock Spliit client."""
        client = MagicMock()
        client.get_expense.return_value = {
            "title": "Test Store",
            "amount": 5000,
            "expenseDate": "2024-01-15T00:00:00Z",
            "category": {"id": 1},
        }
        return client

    def test_updates_amount(self, mock_spliit_client):
        """Test updating expense amount."""
        session = MagicMock()

        result = update_spliit_expense(
            mock_spliit_client,
            "expense-123",
            session,
            {},
            new_amount_cents=6000,
        )

        assert result is True
        mock_spliit_client.update_expense.assert_called_once()
        call_kwargs = mock_spliit_client.update_expense.call_args[1]
        assert call_kwargs["amount_cents"] == 6000

    def test_updates_date(self, mock_spliit_client):
        """Test updating expense date."""
        session = MagicMock()
        new_date = datetime.date(2024, 2, 20)

        result = update_spliit_expense(
            mock_spliit_client,
            "expense-123",
            session,
            {},
            new_date=new_date,
        )

        assert result is True
        mock_spliit_client.update_expense.assert_called_once()
        call_kwargs = mock_spliit_client.update_expense.call_args[1]
        assert call_kwargs["expense_date"] == new_date

    def test_returns_false_when_expense_not_found(self, mock_spliit_client):
        """Test that False is returned when expense is not found."""
        mock_spliit_client.get_expense.return_value = None
        session = MagicMock()

        result = update_spliit_expense(
            mock_spliit_client,
            "nonexistent",
            session,
            {},
            new_amount_cents=6000,
        )

        assert result is False
        mock_spliit_client.update_expense.assert_not_called()

    def test_returns_false_on_exception(self, mock_spliit_client):
        """Test that False is returned on update exception."""
        mock_spliit_client.update_expense.side_effect = Exception("API error")
        session = MagicMock()

        result = update_spliit_expense(
            mock_spliit_client,
            "expense-123",
            session,
            {},
            new_amount_cents=6000,
        )

        assert result is False


class TestDeleteSpliitExpense:
    """Tests for the delete_spliit_expense function."""

    def test_deletes_expense(self):
        """Test successfully deleting an expense."""
        mock_client = MagicMock()

        result = delete_spliit_expense(mock_client, "expense-123")

        assert result is True
        mock_client.delete_expense.assert_called_once_with("expense-123")

    def test_returns_false_on_exception(self):
        """Test that False is returned on delete exception."""
        mock_client = MagicMock()
        mock_client.delete_expense.side_effect = Exception("API error")

        result = delete_spliit_expense(mock_client, "expense-123")

        assert result is False
