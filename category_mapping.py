"""
Category mapping between Spliit and Actual Budget.
"""

import json
import logging
import os

from sqlmodel import Session
from actual.database import Categories

from spliit import SpliitClient
from actual_helpers import get_category_by_name

logger = logging.getLogger(__name__)


def load_category_mapping(file_path: str) -> dict[str, str]:
    """
    Load category mapping from a JSON file.

    The JSON file should be a simple object mapping Spliit category names
    to Actual category names:

    {
        "Groceries": "Food",
        "Dining Out": "Restaurants",
        "Gas/Fuel": "Auto & Transport"
    }

    Spliit category names can be:
    - Full path: "Food and Drink/Groceries"
    - Just the name: "Groceries" (will match any category with that name)

    Args:
        file_path: Path to the JSON file

    Returns:
        Dict mapping Spliit category names to Actual category names
    """
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r") as f:
            mapping = json.load(f)

        if not isinstance(mapping, dict):
            logger.error(f"Category mapping file must contain a JSON object, got {type(mapping).__name__}")
            return {}

        # Validate all keys and values are strings
        result: dict[str, str] = {}
        for key, value in mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                logger.warning(f"Skipping invalid category mapping: {key} -> {value} (must be strings)")
                continue
            result[key] = value

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse category mapping file {file_path}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load category mapping file {file_path}: {e}")
        return {}


def map_spliit_to_actual_category(
    session: Session,
    spliit_category_id: int,
    category_mapping: dict[str, str],
    spliit_client: SpliitClient,
) -> Categories | None:
    """
    Map a Spliit category ID to an Actual category.

    Args:
        session: The Actual database session
        spliit_category_id: The Spliit category ID from the expense
        category_mapping: The user-defined category mapping
        spliit_client: The Spliit client for category lookups

    Returns:
        The Actual Categories object if a mapping is found, None otherwise
    """
    spliit_category_name = spliit_client.get_category_name_by_id(spliit_category_id)
    if spliit_category_name is None:
        logger.debug(f"No Spliit category name found for ID {spliit_category_id}")
        return None

    # Try full path match first (e.g., "Food and Drink/Groceries")
    if spliit_category_name in category_mapping:
        actual_name = category_mapping[spliit_category_name]
        result = get_category_by_name(session, actual_name)
        logger.debug(f"Mapped Spliit '{spliit_category_name}' -> Actual '{actual_name}' (found: {result is not None})")
        return result

    # Try just the category name (e.g., "Groceries")
    short_name = spliit_category_name.split("/")[-1]
    if short_name in category_mapping:
        actual_name = category_mapping[short_name]
        result = get_category_by_name(session, actual_name)
        logger.debug(f"Mapped Spliit '{short_name}' -> Actual '{actual_name}' (found: {result is not None})")
        return result

    logger.debug(f"No mapping found for Spliit category '{spliit_category_name}' or '{short_name}'")
    return None


def map_actual_to_spliit_category(
    actual_category_name: str | None,
    category_mapping: dict[str, str],
    spliit_client: SpliitClient,
) -> int:
    """
    Map an Actual category name to a Spliit category ID.

    Args:
        actual_category_name: The Actual category name
        category_mapping: The user-defined category mapping (Spliit -> Actual)
        spliit_client: The Spliit client for category lookups

    Returns:
        The Spliit category ID, or 0 (General) if no mapping found
    """
    if actual_category_name is None:
        return 0

    # Build reverse mapping: Actual name -> Spliit name
    # The category_mapping is Spliit -> Actual, so we reverse it
    for spliit_cat, actual_cat in category_mapping.items():
        if actual_cat == actual_category_name:
            # Use spliit_client to look up the category ID
            return spliit_client.get_category_id_by_name(spliit_cat)

    return 0  # Default to "General"
