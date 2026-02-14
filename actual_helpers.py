"""
Helper functions for interacting with Actual Budget.
"""

import datetime
import logging
from decimal import Decimal

from sqlmodel import Session, select
from actual import Changeset, Transactions
from actual.utils.conversions import int_to_date, cents_to_decimal
from actual.queries import get_payee, get_account, create_transaction, create_transaction_from_ids
from actual.database import Categories

logger = logging.getLogger(__name__)


type ChangeDict = dict[str, str | int | bool | None]


CORRELATION_PREFIX = "ref:"
SPLIIT_PREFIX = "spliit:"


def build_correlation_ref(original_id: str, spliit_id: str | None = None) -> str:
    """
    Build the correlation reference string for imported_description.

    Format: ref:{original_id} or ref:{original_id}|spliit:{spliit_id}

    Args:
        original_id: The original Actual transaction ID
        spliit_id: The Spliit expense ID (optional)

    Returns:
        The correlation reference string
    """
    ref = f"{CORRELATION_PREFIX}{original_id}"
    if spliit_id:
        ref += f"|{SPLIIT_PREFIX}{spliit_id}"
    return ref


def parse_correlation_ref(imported_description: str | None) -> tuple[str | None, str | None]:
    """
    Parse the correlation reference string from imported_description.

    Args:
        imported_description: The imported_description field value

    Returns:
        Tuple of (original_transaction_id, spliit_expense_id), either may be None
    """
    if not imported_description:
        return None, None

    original_id = None
    spliit_id = None

    parts = imported_description.split("|")
    for part in parts:
        if part.startswith(CORRELATION_PREFIX):
            original_id = part[len(CORRELATION_PREFIX):]
        elif part.startswith(SPLIIT_PREFIX):
            spliit_id = part[len(SPLIIT_PREFIX):]

    return original_id, spliit_id


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
    # Only update tracking dict if notes were actually in the changeset
    if "notes" in changed_columns:
        existing_transactions[changed_obj.id] = new_notes if isinstance(new_notes, str) else None

    # Skip edits to notes that already have the trigger tag
    # We only want to act on the initial addition of the tag
    if last_notes is not None and trigger_tag in last_notes:
        return None

    if changed_obj.notes is not None and trigger_tag in (new_notes if isinstance(new_notes, str) else ""):
        return changed_obj

    return None


def find_correlated_split_transaction(
    session: Session,
    original_transaction_id: str,
) -> Transactions | None:
    """
    Find a split/deposit transaction that was created for a given original transaction.

    Uses the imported_description field which stores 'ref:{original_id}' or
    'ref:{original_id}|spliit:{spliit_id}'.

    Args:
        session: The Actual database session
        original_transaction_id: The ID of the original #shared transaction

    Returns:
        The correlated split transaction if found, None otherwise
    """
    correlation_prefix = f"{CORRELATION_PREFIX}{original_transaction_id}"
    statement = select(Transactions).where(
        Transactions.imported_description.startswith(correlation_prefix),  # type: ignore
        Transactions.tombstone == False,  # noqa: E712
    )
    return session.exec(statement).first()


def get_spliit_expense_id(split_transaction: Transactions) -> str | None:
    """
    Extract the Spliit expense ID from a split transaction's imported_description.

    Args:
        split_transaction: The split transaction to extract from

    Returns:
        The Spliit expense ID if found, None otherwise
    """
    _, spliit_id = parse_correlation_ref(split_transaction.imported_description)
    return spliit_id


def update_split_spliit_id(
    session: Session,
    split_transaction: Transactions,
    spliit_expense_id: str,
) -> None:
    """
    Update a split transaction to include the Spliit expense ID.

    Args:
        session: The Actual database session
        split_transaction: The split transaction to update
        spliit_expense_id: The Spliit expense ID to add
    """
    original_id, _ = parse_correlation_ref(split_transaction.imported_description)
    if original_id:
        split_transaction.imported_description = build_correlation_ref(
            original_id, spliit_expense_id
        )
        session.flush()


def delete_split_transaction(
    session: Session,
    split_transaction: Transactions,
) -> bool:
    """
    Delete a split transaction by setting its tombstone flag.

    Only deletes if the transaction is not cleared or reconciled.

    Args:
        session: The Actual database session
        split_transaction: The split transaction to delete

    Returns:
        True if deleted, False if skipped (cleared/reconciled)
    """
    # Don't modify cleared or reconciled transactions
    if split_transaction.cleared or split_transaction.reconciled:
        logger.info(
            f"Skipping delete for split transaction {split_transaction.id}: "
            f"cleared={split_transaction.cleared}, reconciled={split_transaction.reconciled}"
        )
        return False

    split_transaction.tombstone = True
    session.flush()
    logger.debug(f"Deleted split transaction {split_transaction.id}")
    return True


def update_split_transaction(
    session: Session,
    split_transaction: Transactions,
    new_amount_cents: int | None = None,
    new_date: int | None = None,
    new_category_id: str | None = None,
) -> bool:
    """
    Update a split transaction with new values from the original transaction.

    Only updates if the transaction is not cleared or reconciled.

    Args:
        session: The Actual database session
        split_transaction: The split transaction to update
        new_amount_cents: New amount in cents (will be halved for split)
        new_date: New date as integer (YYYYMMDD format)
        new_category_id: New category ID

    Returns:
        True if updated, False if skipped (cleared/reconciled)
    """
    # Don't modify cleared or reconciled transactions
    if split_transaction.cleared or split_transaction.reconciled:
        logger.info(
            f"Skipping update for split transaction {split_transaction.id}: "
            f"cleared={split_transaction.cleared}, reconciled={split_transaction.reconciled}"
        )
        return False

    updated = False

    if new_amount_cents is not None:
        # Split transaction gets half the original amount (negated for deposit)
        split_amount = cents_to_decimal(-new_amount_cents) / 2
        split_transaction.set_amount(split_amount)
        logger.debug(f"Updated split transaction amount to {split_amount}")
        updated = True

    if new_date is not None:
        date_value = int_to_date(new_date)
        split_transaction.set_date(date_value)
        logger.debug(f"Updated split transaction date to {date_value}")
        updated = True

    if new_category_id is not None:
        split_transaction.category_id = new_category_id
        logger.debug(f"Updated split transaction category to {new_category_id}")
        updated = True

    if updated:
        session.flush()

    return updated


def create_deposit_transaction(
    original: Transactions,
    change: ChangeDict,
    session: Session,
    payee_name: str,
    account_name: str,
    auto_tag: str = "#auto",
    spliit_expense_id: str | None = None,
) -> Transactions:
    """
    Create a deposit transaction for half the amount of a shared expense.

    The created transaction stores a reference to the original transaction
    and optionally the Spliit expense ID in the imported_description field.

    Args:
        original: The original transaction being split
        change: The changeset with any updated values
        session: The Actual database session
        payee_name: Name of the payee for the deposit
        account_name: Name of the account for the deposit
        auto_tag: Tag to add to the deposit transaction notes
        spliit_expense_id: The Spliit expense ID (optional)

    Returns:
        The created deposit transaction
    """
    if original.amount is None:
        raise ValueError("Original transaction has no amount")

    if original.date is None:
        raise ValueError("Original transaction has no date")

    if original.id is None:
        raise ValueError("Original transaction has no ID")

    destination_payee = get_payee(session, payee_name)
    if destination_payee is None:
        raise ValueError(f"Payee '{payee_name}' not found")

    destination_account = get_account(session, account_name)
    if destination_account is None or destination_account.id is None:
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

    deposit = create_transaction_from_ids(
        session,
        date=date_to_use,
        account_id=destination_account.id,
        payee_id=destination_payee.id if destination_payee else None,
        notes=f"{original_payee_name} {auto_tag}",
        category_id=category_to_use.id if category_to_use else None,
        amount=-amount_to_use / 2,
    )

    # Store reference to original transaction and Spliit expense for edit propagation
    deposit.imported_description = build_correlation_ref(original.id, spliit_expense_id)

    session.flush()
    return deposit


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
