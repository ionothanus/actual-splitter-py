"""
Helper functions for Spliit integration.
"""

import datetime
import logging

from actual import Transactions
from actual.utils.conversions import int_to_date
from actual.database import Categories

from spliit import SpliitClient
from actual_helpers import ChangeDict, create_transaction_from_spliit
from category_mapping import map_spliit_to_actual_category, map_actual_to_spliit_category

logger = logging.getLogger(__name__)


def create_spliit_expense(
    original: Transactions,
    change: ChangeDict,
    spliit_client: SpliitClient,
    session,
    category_mapping: dict[str, str],
) -> str | None:
    """
    Create a corresponding expense in Spliit for a shared transaction.

    Args:
        original: The original Actual transaction
        change: The changeset with any updated values
        spliit_client: The Spliit API client
        session: The Actual database session
        category_mapping: The user-defined category mapping

    Returns:
        The Spliit expense ID if created successfully, None otherwise
    """
    if original.amount is None:
        raise ValueError("Original transaction has no amount")

    if original.date is None:
        raise ValueError("Original transaction has no date")

    # Get the amount from the change if it was updated, otherwise from original
    new_amount = change.get("amount")
    if new_amount is not None:
        amount_cents = abs(int(new_amount))
    else:
        amount_cents = abs(original.amount)

    # Get the date from the change if it was updated, otherwise from original
    new_date = change.get("date")
    if new_date is not None:
        expense_date = int_to_date(int(new_date))
    else:
        expense_date = original.get_date()

    # Build the title from the payee name
    payee_name = "Unknown payee"
    if original.payee is not None and original.payee.name is not None:
        payee_name = original.payee.name

    # Map Actual category to Spliit category if configured
    actual_category_name = None
    new_category = change.get("category")
    if new_category is not None and isinstance(new_category, str):
        cat = session.get(Categories, new_category)
        if cat is not None:
            actual_category_name = cat.name
    elif original.category is not None:
        actual_category_name = original.category.name

    spliit_category_id = map_actual_to_spliit_category(
        actual_category_name, category_mapping, spliit_client
    )

    result = spliit_client.create_expense(
        title=payee_name,
        amount_cents=amount_cents,
        expense_date=expense_date,
        category=spliit_category_id,
        notes="Auto-created from Actual Budget",
    )
    expense_id = result.get("expenseId") if result else None
    logger.debug(f"Created Spliit expense {expense_id} for: {payee_name} (category: {spliit_category_id})")
    return expense_id


def update_spliit_expense(
    spliit_client: SpliitClient,
    expense_id: str,
    session,
    category_mapping: dict[str, str],
    new_amount_cents: int | None = None,
    new_date: datetime.date | None = None,
    new_category_id: str | None = None,
) -> bool:
    """
    Update an existing Spliit expense.

    Args:
        spliit_client: The Spliit API client
        expense_id: The Spliit expense ID to update
        session: The Actual database session
        category_mapping: The user-defined category mapping
        new_amount_cents: New amount in cents (if changed)
        new_date: New date (if changed)
        new_category_id: New Actual category ID (if changed)

    Returns:
        True if updated successfully, False otherwise
    """
    # Get the existing expense to preserve unchanged fields
    existing = spliit_client.get_expense(expense_id)
    if existing is None:
        logger.warning(f"Spliit expense {expense_id} not found for update")
        return False

    # Get current values from existing expense
    title = existing.get("title", "Unknown")
    amount_cents = existing.get("amount", 0)
    expense_date_str = existing.get("expenseDate")

    if expense_date_str:
        try:
            expense_date = datetime.datetime.fromisoformat(
                expense_date_str.replace("Z", "+00:00")
            ).date()
        except ValueError:
            expense_date = datetime.date.today()
    else:
        expense_date = datetime.date.today()

    # Get current category
    category_obj = existing.get("category", {})
    spliit_category = category_obj.get("id", 0) if category_obj else 0

    # Apply updates
    if new_amount_cents is not None:
        amount_cents = abs(new_amount_cents)

    if new_date is not None:
        expense_date = new_date

    if new_category_id is not None:
        # Map Actual category to Spliit category
        cat = session.get(Categories, new_category_id)
        if cat is not None:
            spliit_category = map_actual_to_spliit_category(
                cat.name, category_mapping, spliit_client
            )

    try:
        spliit_client.update_expense(
            expense_id=expense_id,
            title=title,
            amount_cents=amount_cents,
            expense_date=expense_date,
            category=spliit_category,
            notes="Auto-updated from Actual Budget",
        )
        logger.debug(f"Updated Spliit expense {expense_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to update Spliit expense {expense_id}: {e}")
        return False


def delete_spliit_expense(
    spliit_client: SpliitClient,
    expense_id: str,
) -> bool:
    """
    Delete a Spliit expense.

    Args:
        spliit_client: The Spliit API client
        expense_id: The Spliit expense ID to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        spliit_client.delete_expense(expense_id)
        logger.debug(f"Deleted Spliit expense {expense_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete Spliit expense {expense_id}: {e}")
        return False


def calculate_my_share(expense: dict, my_participant_id: str) -> int:
    """
    Calculate my share of a Spliit expense in cents.

    Args:
        expense: The Spliit expense object
        my_participant_id: My participant ID in the group

    Returns:
        My share in cents (positive number), or 0 if I'm not involved
    """
    split_mode = expense.get("splitMode", "EVENLY")
    total_amount = expense.get("amount", 0)
    paid_for = expense.get("paidFor", [])

    # Find my entry in paidFor
    my_entry = None
    for entry in paid_for:
        participant = entry.get("participant", {})
        if participant.get("id") == my_participant_id:
            my_entry = entry
            break

    if my_entry is None:
        return 0  # I'm not part of this expense

    if split_mode == "EVENLY":
        return total_amount // len(paid_for)
    elif split_mode == "BY_SHARES":
        total_shares = sum(e.get("shares", 100) for e in paid_for)
        my_shares = my_entry.get("shares", 100)
        return (total_amount * my_shares) // total_shares
    elif split_mode == "BY_PERCENTAGE":
        my_percentage = my_entry.get("shares", 0)
        return (total_amount * my_percentage) // 10000
    elif split_mode == "BY_AMOUNT":
        return my_entry.get("shares", 0)
    else:
        # Unknown split mode, fall back to even split
        return total_amount // len(paid_for)


def process_spliit_expenses(
    spliit_client: SpliitClient,
    session,
    processed_spliit_ids: set[str],
    category_mapping: dict[str, str],
    splitter_payee: str,
    splitter_account: str,
) -> bool:
    """
    Poll Spliit for new expenses and create Actual transactions.

    Args:
        spliit_client: The Spliit API client
        session: The Actual database session
        processed_spliit_ids: Set of already-processed Spliit expense IDs
        category_mapping: The user-defined category mapping
        splitter_payee: The payee name for created transactions
        splitter_account: The account name for created transactions

    Returns:
        True if any new transactions were created
    """
    my_participant_id = spliit_client.payer_id
    created_any = False

    try:
        expenses = spliit_client.list_expenses(limit=50)
    except Exception as e:
        logger.error(f"Failed to fetch Spliit expenses: {e}")
        return False

    for expense in expenses:
        expense_id = expense.get("id")
        if not expense_id or expense_id in processed_spliit_ids:
            continue

        # Mark as processed regardless of whether we create a transaction
        processed_spliit_ids.add(expense_id)

        # Skip expenses paid by me (those go Actual -> Spliit, not the reverse)
        paid_by = expense.get("paidBy", {})
        if paid_by.get("id") == my_participant_id:
            continue

        # Skip reimbursements
        if expense.get("isReimbursement", False):
            continue

        # Calculate my share
        my_share = calculate_my_share(expense, my_participant_id)
        if my_share <= 0:
            continue

        # Get expense details
        title = expense.get("title", "Unknown expense")
        payer_name = paid_by.get("name", "Unknown")
        expense_date_str = expense.get("expenseDate")

        # Category is an object with id, grouping, name
        category_obj = expense.get("category", {})
        spliit_category_id = category_obj.get("id", 0) if category_obj else 0
        logger.debug(f"Spliit expense '{title}': category = {category_obj}, extracted id = {spliit_category_id}")

        # Parse the date
        if expense_date_str:
            try:
                expense_date = datetime.datetime.fromisoformat(
                    expense_date_str.replace("Z", "+00:00")
                ).date()
            except ValueError:
                expense_date = datetime.date.today()
        else:
            expense_date = datetime.date.today()

        # Map Spliit category to Actual category if configured
        actual_category = map_spliit_to_actual_category(
            session, spliit_category_id, category_mapping, spliit_client
        )

        # Create the Actual transaction
        create_transaction_from_spliit(
            session=session,
            payee_name=splitter_payee,
            account_name=splitter_account,
            date=expense_date,
            amount_cents=my_share,
            category=actual_category,
            title=title,
            payer_name=payer_name,
        )

        logger.info(f"Created Actual transaction for Spliit expense: {title} ({my_share/100:.2f})")
        created_any = True

    return created_any
