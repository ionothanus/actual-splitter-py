import time
import datetime
import os
import logging
import threading
from sys import stdout

from sqlmodel import Session
from actual import Actual, Changeset, Transactions
from actual.utils.conversions import int_to_date, cents_to_decimal
from actual.queries import get_transactions, get_payee, get_account, create_transaction
from actual.database import Categories
from dotenv import load_dotenv

from spliit import create_spliit_client_from_env, SpliitClient

load_dotenv()

env_baseurl = os.getenv("ACTUAL_BASEURL")
env_password = os.getenv("ACTUAL_PASSWORD")
env_budget = os.getenv("ACTUAL_BUDGET")
env_splitterpayeeid = os.getenv("ACTUAL_SPLITTER_PAYEE_ID")
env_splitteraccountid = os.getenv("ACTUAL_SPLITTER_ACCOUNT_ID")
env_logging_level = os.getenv("LOGGING_LEVEL", "INFO").upper()
env_actual_poll_interval = int(os.getenv("ACTUAL_POLL_INTERVAL", "5"))
env_spliit_poll_interval = int(os.getenv("SPLIIT_POLL_INTERVAL", "30"))
env_category_mapping_file = os.getenv("SPLIIT_CATEGORY_MAPPING_FILE", "category-mapping.json")
env_trigger_tag = os.getenv("ACTUAL_TRIGGER_TAG", "#shared")

logger = logging.getLogger(__name__)
logging.getLogger().addHandler(logging.StreamHandler(stdout))
logger.setLevel(env_logging_level)


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
    import json

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


def get_actual_category_by_name(session: Session, category_name: str) -> Categories | None:
    """
    Look up an Actual category by name.

    Args:
        session: The Actual database session
        category_name: The name of the category to find

    Returns:
        The Categories object if found, None otherwise
    """
    from sqlmodel import select

    statement = select(Categories).where(Categories.name == category_name)
    return session.exec(statement).first()


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
        result = get_actual_category_by_name(session, actual_name)
        logger.debug(f"Mapped Spliit '{spliit_category_name}' -> Actual '{actual_name}' (found: {result is not None})")
        return result

    # Try just the category name (e.g., "Groceries")
    short_name = spliit_category_name.split("/")[-1]
    if short_name in category_mapping:
        actual_name = category_mapping[short_name]
        result = get_actual_category_by_name(session, actual_name)
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


# Load category mapping from file at startup
category_mapping = load_category_mapping(env_category_mapping_file)
if category_mapping:
    logger.info(f"Loaded {len(category_mapping)} category mappings from {env_category_mapping_file}")


type ChangeDict = dict[str, str | int | bool | None]

def detect_new_shared_transaction(change: Changeset, changed_columns: ChangeDict, session: Session, existing_transactions: dict[str, str | None]) -> Transactions | None:    
    changed_obj: Transactions = change.from_orm(session) # type: ignore

    if (changed_obj is None or changed_obj.id is None):
        logger.warning("Warning: Changed transaction has no ID")
        return None

    last_notes = existing_transactions.get(changed_obj.id)
    new_notes = changed_columns.get("notes")
    existing_transactions[changed_obj.id] = new_notes if isinstance(new_notes, str) else None

    # Skip edits to notes that already have the trigger tag - we only want to act on the initial addition of the tag here
    if last_notes is not None and env_trigger_tag in last_notes:
        return None

    if changed_obj.notes is not None and env_trigger_tag in new_notes if isinstance(new_notes, str) else "":
        return changed_obj

    return None

def create_spliit_expense(
    original: Transactions,
    change: ChangeDict,
    spliit_client: SpliitClient,
    session: Session,
) -> None:
    """Create a corresponding expense in Spliit for a shared transaction."""
    if original.amount is None:
        raise ValueError("Original transaction has no amount")

    if original.date is None:
        raise ValueError("Original transaction has no date")

    # Get the amount from the change if it was updated, otherwise from original
    new_amount = change.get("amount")
    if new_amount is not None:
        amount_cents = abs(int(new_amount))
    else:
        # original.amount is in cents, negative for expenses
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
        # Category was changed, look it up
        cat = session.get(Categories, new_category)
        if cat is not None:
            actual_category_name = cat.name
    elif original.category is not None:
        actual_category_name = original.category.name

    spliit_category_id = map_actual_to_spliit_category(actual_category_name, category_mapping, spliit_client)

    spliit_client.create_expense(
        title=payee_name,
        amount_cents=amount_cents,
        expense_date=expense_date,
        category=spliit_category_id,
        notes=f"Auto-created from Actual Budget",
    )
    logger.info(f"Created Spliit expense for: {payee_name} (category: {spliit_category_id})")


def create_deposit_transaction(original: Transactions, change: ChangeDict, session: Session):
    if (original.amount is None):
        raise ValueError("Original transaction has no amount")
    
    if (original.date is None):
        raise ValueError("Original transaction has no date")
    
    if (env_splitterpayeeid is None):
        raise ValueError("Environment variable ACTUAL_SPLITTER_PAYEE_ID is not set")
    
    if (env_splitteraccountid is None):
        raise ValueError("Environment variable ACTUAL_SPLITTER_ACCOUNT_ID is not set")
    
    destination_payee = get_payee(session, env_splitterpayeeid)
    if destination_payee is None:
        raise ValueError(f"Payee with ID {env_splitterpayeeid} not found")
    
    destination_account = get_account(session, env_splitteraccountid)
    if destination_account is None:
        raise ValueError(f"Account with ID {env_splitteraccountid} not found")
    
    # TODO: this will fail on subsequent changes
    # i.e.: edit the amount, then edit the note - the second change wil create a split
    # based on the original amount, because it didn't happen on the change that added the #shared tag
    # and the original transaction still has the first (pre-change) amount.
    # Doesn't matter while we don't support editing transactions.

    new_date = change.get("date")
    if new_date is not None:
        date_to_use = int_to_date(int(new_date))
    else:
        date_to_use = original.get_date()

    new_amount = change.get("amount")
    if new_amount is not None:
        amount_to_use = cents_to_decimal(new_amount) # type: ignore
    else:
        amount_to_use = original.get_amount()

    new_category = change.get("category")
    if new_category is not None and isinstance(new_category, str):
        category_to_use = session.get(Categories, new_category)
    else:
        category_to_use = original.category

    create_transaction(
        session,
        account=destination_account,
        date=date_to_use,
        amount=-amount_to_use/2,
        payee=destination_payee,
        category=category_to_use,
        notes=f"{'Unknown payee' if original.payee is None or original.payee.name is None else original.payee.name} #auto",
    )

    session.flush()


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
        # Each participant pays an equal share
        return total_amount // len(paid_for)
    elif split_mode == "BY_SHARES":
        # Shares are proportional (shares are stored as value * 100)
        total_shares = sum(e.get("shares", 100) for e in paid_for)
        my_shares = my_entry.get("shares", 100)
        return (total_amount * my_shares) // total_shares
    elif split_mode == "BY_PERCENTAGE":
        # Shares represent percentage * 100 (e.g., 5000 = 50%)
        my_percentage = my_entry.get("shares", 0)
        return (total_amount * my_percentage) // 10000
    elif split_mode == "BY_AMOUNT":
        # Shares are the exact amount in cents
        return my_entry.get("shares", 0)
    else:
        # Unknown split mode, fall back to even split
        return total_amount // len(paid_for)


def process_spliit_expenses(
    spliit_client: SpliitClient,
    session: Session,
    processed_spliit_ids: set[str],
) -> bool:
    """
    Poll Spliit for new expenses and create Actual transactions.

    Args:
        spliit_client: The Spliit API client
        session: The Actual database session
        processed_spliit_ids: Set of already-processed Spliit expense IDs

    Returns:
        True if any new transactions were created
    """
    if env_splitterpayeeid is None or env_splitteraccountid is None:
        return False

    destination_payee = get_payee(session, env_splitterpayeeid)
    if destination_payee is None:
        logger.error(f"Payee with ID {env_splitterpayeeid} not found")
        return False

    destination_account = get_account(session, env_splitteraccountid)
    if destination_account is None:
        logger.error(f"Account with ID {env_splitteraccountid} not found")
        return False

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

        # Parse the date (format: "2026-02-13T00:00:00.000Z")
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

        # Create the Actual transaction (negative = expense/money I owe)
        create_transaction(
            session,
            account=destination_account,
            date=expense_date,
            amount=cents_to_decimal(-my_share),
            payee=destination_payee,
            category=actual_category,
            notes=f"{title} (paid by {payer_name}) #spliit",
        )

        logger.info(f"Created Actual transaction for Spliit expense: {title} ({my_share/100:.2f})")
        created_any = True

    return created_any


def poll_actual(
    actual: Actual,
    spliit_client: SpliitClient | None,
    lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    """
    Poll Actual Budget for new transactions with the trigger tag.
    Runs in its own thread with independent timing.
    """
    # Only load the last month of transactions for performance reasons.
    existing_transactions = get_transactions(
        actual.session,
        start_date=datetime.datetime.now().date() - datetime.timedelta(days=30),
    )
    existing_transaction_notes_map = {t.id: t.notes for t in existing_transactions if t.id is not None}
    transaction_ids = {t.id for t in existing_transactions}

    while not stop_event.is_set():
        try:
            with lock:
                changes = actual.sync()
                logger.debug(f"Detected {len(changes)} Actual changes")
                logger.debug(changes)
                local_changes = False

                for change in changes:
                    changed_columns = {col.name: val for col, val in change.values.items()}
                    table = change.table

                    if table is not Transactions:
                        continue

                    # deleted transactions are ignored
                    if changed_columns.get("tombstone"):
                        continue

                    # only process new transactions
                    if change.id in transaction_ids:
                        continue

                    transaction_ids.add(change.id)

                    original = detect_new_shared_transaction(
                        change, changed_columns, actual.session, existing_transaction_notes_map
                    )
                    if original is not None:
                        local_changes = True
                        create_deposit_transaction(original, changed_columns, actual.session)
                        logger.info(f"Created deposit transaction for original ID {original.id}")

                        # Also create expense in Spliit if configured
                        if spliit_client:
                            try:
                                create_spliit_expense(original, changed_columns, spliit_client, actual.session)
                            except Exception as e:
                                logger.error(f"Failed to create Spliit expense: {e}")

                if local_changes:
                    actual.commit()

                if len(changes) > 0:
                    # Changesets never seem to apply to the local copy of the database,
                    # so reload the transaction table when we know there are changes
                    existing_transactions = get_transactions(
                        actual.session,
                        start_date=datetime.datetime.now().date() - datetime.timedelta(days=30),
                    )
                    existing_transaction_notes_map = {t.id: t.notes for t in existing_transactions if t.id is not None}

        except Exception as e:
            logger.error(f"Error in Actual polling loop: {e}")

        time.sleep(env_actual_poll_interval)


def poll_spliit(
    actual: Actual,
    spliit_client: SpliitClient,
    processed_spliit_ids: set[str],
    lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    """
    Poll Spliit for new expenses paid by others.
    Runs in its own thread with independent timing.
    """
    while not stop_event.is_set():
        try:
            logger.debug("Polling Spliit for new expenses...")
            with lock:
                if process_spliit_expenses(spliit_client, actual.session, processed_spliit_ids):
                    actual.commit()
        except Exception as e:
            logger.error(f"Failed to process Spliit expenses: {e}")

        time.sleep(env_spliit_poll_interval)


def main() -> None:
    if (env_baseurl is None) or (env_password is None) or (env_budget is None) or (env_splitterpayeeid is None):
        raise ValueError("Missing one of ACTUAL_BASEURL, ACTUAL_PASSWORD, ACTUAL_BUDGET, ACTUAL_SPLITTER_PAYEE_ID in .env")

    # Initialize Spliit client (optional - will be None if env vars not set)
    spliit_client = create_spliit_client_from_env()
    if spliit_client:
        logger.info("Spliit integration enabled")
    else:
        logger.info("Spliit integration disabled (SPLIIT_GROUP_ID and SPLIIT_PAYER_ID not set)")

    with Actual(base_url=env_baseurl, file=env_budget, password=env_password) as actual:
        # Lock to synchronize access to the Actual session between threads
        lock = threading.Lock()
        stop_event = threading.Event()

        # Track processed Spliit expense IDs to avoid creating duplicates
        processed_spliit_ids: set[str] = set()
        if spliit_client:
            try:
                initial_expenses = spliit_client.list_expenses(limit=50)
                for e in initial_expenses:
                    expense_id = e.get("id")
                    if expense_id:
                        processed_spliit_ids.add(expense_id)
                logger.info(f"Loaded {len(processed_spliit_ids)} existing Spliit expenses")
            except Exception as e:
                logger.warning(f"Failed to load initial Spliit expenses: {e}")

        # Start polling threads
        threads: list[threading.Thread] = []

        actual_thread = threading.Thread(
            target=poll_actual,
            args=(actual, spliit_client, lock, stop_event),
            daemon=True,
            name="ActualPoller",
        )
        threads.append(actual_thread)
        actual_thread.start()
        logger.info(f"Started Actual polling thread (interval: {env_actual_poll_interval}s)")

        if spliit_client:
            spliit_thread = threading.Thread(
                target=poll_spliit,
                args=(actual, spliit_client, processed_spliit_ids, lock, stop_event),
                daemon=True,
                name="SpliitPoller",
            )
            threads.append(spliit_thread)
            spliit_thread.start()
            logger.info(f"Started Spliit polling thread (interval: {env_spliit_poll_interval}s)")

        # Wait for threads (they run forever until interrupted)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            stop_event.set()
            for t in threads:
                t.join(timeout=5)

if __name__ == "__main__":
    main()
