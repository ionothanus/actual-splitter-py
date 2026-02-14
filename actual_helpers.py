"""
Helper functions for interacting with Actual Budget.
"""

import datetime
import logging
from decimal import Decimal

from sqlmodel import Session, select
from actual import Changeset, Transactions
from actual.utils.conversions import int_to_date, cents_to_decimal
from actual.queries import get_payee, get_account, create_transaction
from actual.database import Categories

logger = logging.getLogger(__name__)


type ChangeDict = dict[str, str | int | bool | None]


def get_category_by_name(session: Session, category_name: str) -> Categories | None:
    """
    Look up an Actual category by name.

    Args:
        session: The Actual database session
        category_name: The name of the category to find

    Returns:
        The Categories object if found, None otherwise
    """
    statement = select(Categories).where(Categories.name == category_name)
    return session.exec(statement).first()


def detect_new_shared_transaction(
    change: Changeset,
    changed_columns: ChangeDict,
    session: Session,
    existing_transactions: dict[str, str | None],
    trigger_tag: str,
) -> Transactions | None:
    """
    Detect if a changeset represents a new transaction with the trigger tag.

    Args:
        change: The changeset from Actual sync
        changed_columns: Dict of column names to new values
        session: The Actual database session
        existing_transactions: Map of transaction ID to notes for tracking
        trigger_tag: The tag that triggers splitting (e.g., "#shared")

    Returns:
        The transaction if it's newly tagged, None otherwise
    """
    changed_obj: Transactions = change.from_orm(session)  # type: ignore

    if changed_obj is None or changed_obj.id is None:
        logger.warning("Warning: Changed transaction has no ID")
        return None

    last_notes = existing_transactions.get(changed_obj.id)
    new_notes = changed_columns.get("notes")
    existing_transactions[changed_obj.id] = new_notes if isinstance(new_notes, str) else None

    # Skip edits to notes that already have the trigger tag
    # We only want to act on the initial addition of the tag
    if last_notes is not None and trigger_tag in last_notes:
        return None

    if changed_obj.notes is not None and trigger_tag in (new_notes if isinstance(new_notes, str) else ""):
        return changed_obj

    return None


def create_deposit_transaction(
    original: Transactions,
    change: ChangeDict,
    session: Session,
    payee_name: str,
    account_name: str,
    auto_tag: str = "#auto",
) -> None:
    """
    Create a deposit transaction for half the amount of a shared expense.

    Args:
        original: The original transaction being split
        change: The changeset with any updated values
        session: The Actual database session
        payee_name: Name of the payee for the deposit
        account_name: Name of the account for the deposit
        auto_tag: Tag to add to the deposit transaction notes
    """
    if original.amount is None:
        raise ValueError("Original transaction has no amount")

    if original.date is None:
        raise ValueError("Original transaction has no date")

    destination_payee = get_payee(session, payee_name)
    if destination_payee is None:
        raise ValueError(f"Payee '{payee_name}' not found")

    destination_account = get_account(session, account_name)
    if destination_account is None:
        raise ValueError(f"Account '{account_name}' not found")

    # Get date from change if updated, otherwise from original
    new_date = change.get("date")
    if new_date is not None:
        date_to_use = int_to_date(int(new_date))
    else:
        date_to_use = original.get_date()

    # Get amount from change if updated, otherwise from original
    new_amount = change.get("amount")
    if new_amount is not None:
        amount_to_use = cents_to_decimal(new_amount)  # type: ignore
    else:
        amount_to_use = original.get_amount()

    # Get category from change if updated, otherwise from original
    new_category = change.get("category")
    if new_category is not None and isinstance(new_category, str):
        category_to_use = session.get(Categories, new_category)
    else:
        category_to_use = original.category

    # Build notes from original payee name
    original_payee_name = "Unknown payee"
    if original.payee is not None and original.payee.name is not None:
        original_payee_name = original.payee.name

    create_transaction(
        session,
        account=destination_account,
        date=date_to_use,
        amount=-amount_to_use / 2,
        payee=destination_payee,
        category=category_to_use,
        notes=f"{original_payee_name} {auto_tag}",
    )

    session.flush()


def create_transaction_from_spliit(
    session: Session,
    payee_name: str,
    account_name: str,
    date: datetime.date,
    amount_cents: int,
    category: Categories | None,
    title: str,
    payer_name: str,
    tag: str = "#spliit",
) -> None:
    """
    Create an Actual transaction from a Spliit expense.

    Args:
        session: The Actual database session
        payee_name: Name of the payee for the transaction
        account_name: Name of the account for the transaction
        date: The transaction date
        amount_cents: The amount in cents (positive = my share to pay)
        category: The Actual category (or None)
        title: The expense title
        payer_name: Name of who paid
        tag: Tag to add to notes
    """
    destination_payee = get_payee(session, payee_name)
    if destination_payee is None:
        raise ValueError(f"Payee '{payee_name}' not found")

    destination_account = get_account(session, account_name)
    if destination_account is None:
        raise ValueError(f"Account '{account_name}' not found")

    create_transaction(
        session,
        account=destination_account,
        date=date,
        amount=cents_to_decimal(-amount_cents),  # negative = expense
        payee=destination_payee,
        category=category,
        notes=f"{title} (paid by {payer_name}) {tag}",
    )
