"""Tests for spliit_helpers.py"""

import pytest
from spliit_helpers import calculate_my_share


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
