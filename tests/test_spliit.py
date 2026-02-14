"""Tests for spliit.py"""

import pytest
from unittest.mock import patch, MagicMock
import json

from spliit import SpliitClient, create_spliit_client_from_env


class TestSpliitClient:
    """Tests for SpliitClient class."""

    @pytest.fixture
    def client(self):
        """Create a SpliitClient instance for testing."""
        return SpliitClient(
            base_url="https://spliit.app",
            group_id="test-group-123",
            payer_id="payer-456",
        )

    def test_init(self, client):
        """Test client initialization."""
        assert client.base_url == "https://spliit.app"
        assert client.group_id == "test-group-123"
        assert client.payer_id == "payer-456"

    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is stripped from base URL."""
        client = SpliitClient(
            base_url="https://spliit.app/",
            group_id="test",
            payer_id="payer",
        )
        assert client.base_url == "https://spliit.app"

    def test_trpc_url(self, client):
        """Test tRPC URL generation."""
        url = client._trpc_url("groups.get")
        assert url == "https://spliit.app/api/trpc/groups.get"

    @patch("spliit.requests.get")
    def test_get_categories_caches_result(self, mock_get, client):
        """Test that get_categories caches the result."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "data": {
                    "json": {
                        "categories": [
                            {"id": 1, "grouping": "Food", "name": "Groceries"},
                            {"id": 2, "grouping": "Food", "name": "Dining Out"},
                        ]
                    }
                }
            }
        }
        mock_get.return_value = mock_response

        # First call
        result1 = client.get_categories()
        # Second call (should use cache)
        result2 = client.get_categories()

        assert result1 == result2
        assert len(result1) == 2
        # Should only have called the API once
        assert mock_get.call_count == 1

    def test_get_category_name_by_id(self, client):
        """Test getting category name by ID."""
        client._categories = [
            {"id": 1, "grouping": "Food and Drink", "name": "Groceries"},
            {"id": 2, "grouping": "Entertainment", "name": "Movies"},
        ]

        assert client.get_category_name_by_id(1) == "Food and Drink/Groceries"
        assert client.get_category_name_by_id(2) == "Entertainment/Movies"
        assert client.get_category_name_by_id(999) is None

    def test_get_category_id_by_name_full_path(self, client):
        """Test getting category ID by full path name."""
        client._categories = [
            {"id": 1, "grouping": "Food and Drink", "name": "Groceries"},
            {"id": 2, "grouping": "Entertainment", "name": "Movies"},
        ]

        assert client.get_category_id_by_name("Food and Drink/Groceries") == 1
        assert client.get_category_id_by_name("Entertainment/Movies") == 2

    def test_get_category_id_by_name_short_name(self, client):
        """Test getting category ID by short name."""
        client._categories = [
            {"id": 1, "grouping": "Food and Drink", "name": "Groceries"},
            {"id": 2, "grouping": "Entertainment", "name": "Movies"},
        ]

        assert client.get_category_id_by_name("Groceries") == 1
        assert client.get_category_id_by_name("Movies") == 2

    def test_get_category_id_by_name_not_found(self, client):
        """Test getting category ID for unknown category returns 0."""
        client._categories = [
            {"id": 1, "grouping": "Food", "name": "Groceries"},
        ]

        assert client.get_category_id_by_name("Unknown") == 0

    @patch("spliit.requests.get")
    def test_get_participants(self, mock_get, client):
        """Test fetching participants."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "data": {
                    "json": {
                        "group": {
                            "participants": [
                                {"id": "p1", "name": "Alice"},
                                {"id": "p2", "name": "Bob"},
                            ]
                        }
                    }
                }
            }
        }
        mock_get.return_value = mock_response

        participants = client.get_participants()
        assert len(participants) == 2
        assert participants[0]["name"] == "Alice"

    def test_get_participant_name(self, client):
        """Test getting participant name by ID."""
        client._participants = [
            {"id": "p1", "name": "Alice"},
            {"id": "p2", "name": "Bob"},
        ]

        assert client.get_participant_name("p1") == "Alice"
        assert client.get_participant_name("p2") == "Bob"
        assert client.get_participant_name("unknown") == "Unknown"


class TestCreateSpliitClientFromEnv:
    """Tests for create_spliit_client_from_env function."""

    @patch.dict(
        "os.environ",
        {
            "SPLIIT_BASE_URL": "https://custom.spliit.app",
            "SPLIIT_GROUP_ID": "group-123",
            "SPLIIT_PAYER_ID": "payer-456",
        },
    )
    def test_creates_client_with_all_env_vars(self):
        """Test creating client with all environment variables set."""
        client = create_spliit_client_from_env()
        assert client is not None
        assert client.base_url == "https://custom.spliit.app"
        assert client.group_id == "group-123"
        assert client.payer_id == "payer-456"

    @patch.dict(
        "os.environ",
        {
            "SPLIIT_GROUP_ID": "group-123",
            "SPLIIT_PAYER_ID": "payer-456",
        },
        clear=True,
    )
    def test_uses_default_base_url(self):
        """Test that default base URL is used when not set."""
        client = create_spliit_client_from_env()
        assert client is not None
        assert client.base_url == "https://spliit.app"

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_when_missing_required(self):
        """Test that None is returned when required env vars are missing."""
        client = create_spliit_client_from_env()
        assert client is None

    @patch.dict("os.environ", {"SPLIIT_GROUP_ID": "group-123"}, clear=True)
    def test_returns_none_when_payer_id_missing(self):
        """Test that None is returned when SPLIIT_PAYER_ID is missing."""
        client = create_spliit_client_from_env()
        assert client is None

    @patch.dict("os.environ", {"SPLIIT_PAYER_ID": "payer-456"}, clear=True)
    def test_returns_none_when_group_id_missing(self):
        """Test that None is returned when SPLIIT_GROUP_ID is missing."""
        client = create_spliit_client_from_env()
        assert client is None
