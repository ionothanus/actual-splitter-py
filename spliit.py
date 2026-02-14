"""
Spliit API client for creating expenses in a Spliit group.

Spliit uses tRPC, so we call the API via HTTP POST to the tRPC endpoint.
"""

import json
import requests
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


class SpliitClient:
    """Client for interacting with the Spliit tRPC API."""

    def __init__(self, base_url: str, group_id: str, payer_id: str):
        """
        Initialize the Spliit client.

        Args:
            base_url: The base URL of the Spliit instance (e.g., https://spliit.app)
            group_id: The ID of the Spliit group to add expenses to
            payer_id: The participant ID of the payer (you)
        """
        self.base_url = base_url.rstrip("/")
        self.group_id = group_id
        self.payer_id = payer_id
        self._participants: Optional[list[dict]] = None
        self._categories: Optional[list[dict]] = None

    def _trpc_url(self, procedure: str) -> str:
        """Build the tRPC endpoint URL for a procedure."""
        return f"{self.base_url}/api/trpc/{procedure}"

    def get_group(self) -> dict:
        """Fetch group details including participants."""
        url = self._trpc_url("groups.get")
        input_data = {"json": {"groupId": self.group_id}}
        params = {"input": json.dumps(input_data)}

        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        # The procedure returns { group }, so we need to access the nested group
        return data["result"]["data"]["json"]["group"]

    def get_participants(self) -> list[dict]:
        """Get all participants in the group (cached)."""
        if self._participants is not None:
            return self._participants
        group = self.get_group()
        participants: list[dict] = group.get("participants", [])
        self._participants = participants
        return participants

    def get_all_participant_ids(self) -> list[str]:
        """Get all participant IDs in the group."""
        return [p["id"] for p in self.get_participants()]

    def get_participant_name(self, participant_id: str) -> str:
        """Get a participant's name by ID."""
        for p in self.get_participants():
            if p["id"] == participant_id:
                return p.get("name", "Unknown")
        return "Unknown"

    def get_categories(self) -> list[dict]:
        """
        Fetch all available expense categories (cached).

        Returns:
            List of category objects with id, grouping, and name.
        """
        if self._categories is not None:
            return self._categories

        url = self._trpc_url("categories.list")
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()
        categories: list[dict] = data["result"]["data"]["json"]["categories"]
        self._categories = categories
        logger.debug(f"Loaded {len(categories)} Spliit categories")
        return categories

    def get_category_name_by_id(self, category_id: int) -> Optional[str]:
        """
        Get category name (as "grouping/name") by ID.

        Args:
            category_id: The category ID

        Returns:
            Category name in "grouping/name" format, or None if not found.
        """
        for cat in self.get_categories():
            if cat.get("id") == category_id:
                grouping = cat.get("grouping", "Uncategorized")
                name = cat.get("name", "General")
                return f"{grouping}/{name}"
        return None

    def get_category_id_by_name(self, name: str) -> int:
        """
        Get category ID by name.

        Args:
            name: Category name (either "grouping/name" or just "name")

        Returns:
            Category ID, or 0 (General) if not found.
        """
        for cat in self.get_categories():
            grouping = cat.get("grouping", "")
            cat_name = cat.get("name", "")
            full_name = f"{grouping}/{cat_name}"

            # Match full path or just the name
            if name == full_name or name == cat_name:
                return cat.get("id", 0)
        return 0

    def list_expenses(self, limit: int = 50) -> list[dict]:
        """
        List recent expenses in the group.

        Args:
            limit: Maximum number of expenses to fetch

        Returns:
            List of expense objects with id, title, amount, paidBy, paidFor, etc.
        """
        url = self._trpc_url("groups.expenses.list")
        input_data = {
            "json": {
                "groupId": self.group_id,
                "limit": limit,
            }
        }
        params = {"input": json.dumps(input_data)}

        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        return data["result"]["data"]["json"]["expenses"]

    def create_expense(
        self,
        title: str,
        amount_cents: int,
        expense_date: date,
        category: int = 0,
        split_mode: str = "EVENLY",
        is_reimbursement: bool = False,
        notes: Optional[str] = None,
        paid_for_participant_ids: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a new expense in the Spliit group.

        Args:
            title: The expense title/description
            amount_cents: The amount in cents (e.g., 1000 = $10.00)
            expense_date: The date of the expense
            category: Category ID (0 = uncategorized)
            split_mode: How to split the expense (EVENLY, BY_SHARES, BY_PERCENTAGE, BY_AMOUNT)
            is_reimbursement: Whether this is a reimbursement
            notes: Optional notes for the expense
            paid_for_participant_ids: List of participant IDs who share this expense.
                                      If None, splits between all participants.

        Returns:
            The created expense data including its ID.
        """
        url = self._trpc_url("groups.expenses.create")

        # If no specific participants provided, split between all
        if paid_for_participant_ids is None:
            paid_for_participant_ids = self.get_all_participant_ids()

        # Build the paidFor array - for EVENLY split, shares are equal (100 each = 1.00)
        paid_for = [
            {"participant": pid, "shares": 100}
            for pid in paid_for_participant_ids
        ]

        expense_form_values = {
            "title": title,
            "amount": amount_cents,
            "expenseDate": expense_date.isoformat(),
            "category": category,
            "paidBy": self.payer_id,
            "paidFor": paid_for,
            "splitMode": split_mode,
            "isReimbursement": is_reimbursement,
            "saveDefaultSplittingOptions": False,
            "documents": [],
            "recurrenceRule": "NONE",
        }

        if notes:
            expense_form_values["notes"] = notes

        # tRPC mutation format - input wrapped in json key
        payload = {
            "json": {
                "groupId": self.group_id,
                "expenseFormValues": expense_form_values,
                "participantId": self.payer_id,
            }
        }

        logger.debug(f"Creating Spliit expense: {payload}")

        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if not response.ok:
            logger.error(f"Spliit API error: {response.status_code} - {response.text}")
        response.raise_for_status()

        data = response.json()
        result = data["result"]["data"]["json"]
        logger.info(f"Created Spliit expense with ID: {result.get('expenseId')}")
        return result


def create_spliit_client_from_env() -> Optional[SpliitClient]:
    """
    Create a SpliitClient from environment variables.

    Required env vars:
        SPLIIT_BASE_URL: The Spliit instance URL (defaults to https://spliit.app)
        SPLIIT_GROUP_ID: The group ID to add expenses to
        SPLIIT_PAYER_ID: Your participant ID in the group

    Returns:
        SpliitClient if all required env vars are set, None otherwise.
    """
    import os

    base_url = os.getenv("SPLIIT_BASE_URL", "https://spliit.app")
    group_id = os.getenv("SPLIIT_GROUP_ID")
    payer_id = os.getenv("SPLIIT_PAYER_ID")

    if not group_id or not payer_id:
        logger.warning(
            "Spliit integration disabled: SPLIIT_GROUP_ID and SPLIIT_PAYER_ID must be set"
        )
        return None

    return SpliitClient(base_url, group_id, payer_id)
