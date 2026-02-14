"""Tests for category_mapping.py"""

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock

from category_mapping import (
    load_category_mapping,
    map_spliit_to_actual_category,
    map_actual_to_spliit_category,
)


class TestLoadCategoryMapping:
    """Tests for load_category_mapping function."""

    def test_load_valid_mapping(self):
        """Test loading a valid JSON mapping file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"Groceries": "Food", "Dining Out": "Restaurants"}, f)
            f.flush()
            try:
                result = load_category_mapping(f.name)
                assert result == {"Groceries": "Food", "Dining Out": "Restaurants"}
            finally:
                os.unlink(f.name)

    def test_load_nonexistent_file(self):
        """Test loading a file that doesn't exist returns empty dict."""
        result = load_category_mapping("/nonexistent/path/to/file.json")
        assert result == {}

    def test_load_invalid_json(self):
        """Test loading invalid JSON returns empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            f.flush()
            try:
                result = load_category_mapping(f.name)
                assert result == {}
            finally:
                os.unlink(f.name)

    def test_load_non_object_json(self):
        """Test loading JSON that's not an object returns empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(["list", "not", "object"], f)
            f.flush()
            try:
                result = load_category_mapping(f.name)
                assert result == {}
            finally:
                os.unlink(f.name)

    def test_load_skips_non_string_values(self):
        """Test that non-string values are skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            # Note: JSON converts integer keys to strings, so we only test non-string values
            json.dump({"Groceries": "Food", "Invalid": 123, "AlsoInvalid": ["list"]}, f)
            f.flush()
            try:
                result = load_category_mapping(f.name)
                # Only "Groceries": "Food" should be kept
                assert result == {"Groceries": "Food"}
            finally:
                os.unlink(f.name)

    def test_load_empty_object(self):
        """Test loading an empty JSON object."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            f.flush()
            try:
                result = load_category_mapping(f.name)
                assert result == {}
            finally:
                os.unlink(f.name)


class TestMapSpliitToActualCategory:
    """Tests for map_spliit_to_actual_category function."""

    @pytest.fixture
    def mock_spliit_client(self):
        """Create a mock SpliitClient."""
        client = MagicMock()
        client.get_category_name_by_id.side_effect = lambda id: {
            1: "Food and Drink/Groceries",
            2: "Food and Drink/Dining Out",
            3: "Entertainment/Movies",
            0: None,
        }.get(id)
        return client

    @pytest.fixture
    def mock_session(self):
        """Create a mock Actual session."""
        return MagicMock()

    def test_full_path_match(self, mock_session, mock_spliit_client):
        """Test matching by full category path."""
        category_mapping = {"Food and Drink/Groceries": "Food"}

        # Mock get_category_by_name to return a category
        mock_category = MagicMock()
        mock_category.name = "Food"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "category_mapping.get_category_by_name",
                lambda session, name: mock_category if name == "Food" else None,
            )
            result = map_spliit_to_actual_category(
                mock_session, 1, category_mapping, mock_spliit_client
            )
            assert result == mock_category

    def test_short_name_match(self, mock_session, mock_spliit_client):
        """Test matching by short category name."""
        category_mapping = {"Groceries": "Food"}

        mock_category = MagicMock()
        mock_category.name = "Food"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "category_mapping.get_category_by_name",
                lambda session, name: mock_category if name == "Food" else None,
            )
            result = map_spliit_to_actual_category(
                mock_session, 1, category_mapping, mock_spliit_client
            )
            assert result == mock_category

    def test_no_mapping_found(self, mock_session, mock_spliit_client):
        """Test when no mapping exists for the category."""
        category_mapping = {"Other": "Something"}

        result = map_spliit_to_actual_category(
            mock_session, 1, category_mapping, mock_spliit_client
        )
        assert result is None

    def test_unknown_category_id(self, mock_session, mock_spliit_client):
        """Test when the Spliit category ID is not recognized."""
        category_mapping = {"Groceries": "Food"}

        result = map_spliit_to_actual_category(
            mock_session, 0, category_mapping, mock_spliit_client
        )
        assert result is None


class TestMapActualToSpliitCategory:
    """Tests for map_actual_to_spliit_category function."""

    @pytest.fixture
    def mock_spliit_client(self):
        """Create a mock SpliitClient."""
        client = MagicMock()
        client.get_category_id_by_name.side_effect = lambda name: {
            "Groceries": 1,
            "Food and Drink/Groceries": 1,
            "Dining Out": 2,
            "Movies": 3,
        }.get(name, 0)
        return client

    def test_maps_actual_to_spliit(self, mock_spliit_client):
        """Test mapping Actual category to Spliit category."""
        category_mapping = {"Groceries": "Food"}

        result = map_actual_to_spliit_category("Food", category_mapping, mock_spliit_client)
        assert result == 1

    def test_no_mapping_returns_zero(self, mock_spliit_client):
        """Test that unmapped categories return 0 (General)."""
        category_mapping = {"Groceries": "Food"}

        result = map_actual_to_spliit_category("Unknown", category_mapping, mock_spliit_client)
        assert result == 0

    def test_none_category_returns_zero(self, mock_spliit_client):
        """Test that None category returns 0."""
        category_mapping = {"Groceries": "Food"}

        result = map_actual_to_spliit_category(None, category_mapping, mock_spliit_client)
        assert result == 0

    def test_empty_mapping(self, mock_spliit_client):
        """Test with empty category mapping."""
        result = map_actual_to_spliit_category("Food", {}, mock_spliit_client)
        assert result == 0

    def test_multiple_spliit_to_same_actual(self, mock_spliit_client):
        """Test that first match is used when multiple Spliit categories map to same Actual."""
        # In a real dict, insertion order is preserved
        category_mapping = {"Groceries": "Food", "Dining Out": "Food"}

        result = map_actual_to_spliit_category("Food", category_mapping, mock_spliit_client)
        # Should return the first match (Groceries -> 1)
        assert result == 1
