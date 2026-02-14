import time
import datetime
import os
import logging
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

logger = logging.getLogger(__name__)
logging.getLogger().addHandler(logging.StreamHandler(stdout))
logger.setLevel(env_logging_level)


type ChangeDict = dict[str, str | int | bool | None]

def detect_new_shared_transaction(change: Changeset, changed_columns: ChangeDict, session: Session, existing_transactions: dict[str, str | None]) -> Transactions | None:    
    changed_obj: Transactions = change.from_orm(session) # type: ignore

    if (changed_obj is None or changed_obj.id is None):
        logger.warning("Warning: Changed transaction has no ID")
        return None

    last_notes = existing_transactions.get(changed_obj.id)
    new_notes = changed_columns.get("notes")
    existing_transactions[changed_obj.id] = new_notes if isinstance(new_notes, str) else None

    # Skip edits to notes that already have `#shared` - we only want to act on the initial addition of the tag here
    if last_notes is not None and "#shared" in last_notes:
        return None

    if changed_obj.notes is not None and "#shared" in new_notes if isinstance(new_notes, str) else "":
        return changed_obj

    return None

def create_spliit_expense(
    original: Transactions,
    change: ChangeDict,
    spliit_client: SpliitClient,
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

    spliit_client.create_expense(
        title=payee_name,
        amount_cents=amount_cents,
        expense_date=expense_date,
        notes=f"Auto-created from Actual Budget",
    )
    logger.info(f"Created Spliit expense for: {payee_name}")


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
        # Only load the last month of transactions for performance reasons.
        # We'll assume we won't edit transactions older than that for splitting purposes.
        existing_transactions = get_transactions(actual.session, start_date=datetime.datetime.now().date() - datetime.timedelta(days=30))
        existing_transaction_notes_map = {t.id: t.notes for t in existing_transactions if t.id is not None}
 
        transaction_ids = {t.id for t in existing_transactions}
        while True:
            changes = actual.sync()
            logger.info(f"Detected {len(changes)} changes")
            logger.debug(changes)
            local_changes = False
            for change in changes:
                changed_columns = {col.name: val for col, val in change.values.items()}

                table = change.table

                if (table is not Transactions):
                    continue

                # deleted transactions are ignored
                if changed_columns.get("tombstone"):
                    continue

                # only process new transactions
                if change.id in transaction_ids:
                    continue

                transaction_ids.add(change.id)

                original = detect_new_shared_transaction(change, changed_columns, actual.session, existing_transaction_notes_map)
                if original is not None:
                    local_changes = True
                    create_deposit_transaction(original, changed_columns, actual.session)
                    logger.info(f"Created deposit transaction for original ID {original.id}")

                    # Also create expense in Spliit if configured
                    if spliit_client:
                        try:
                            create_spliit_expense(original, changed_columns, spliit_client)
                        except Exception as e:
                            logger.error(f"Failed to create Spliit expense: {e}")
            if local_changes:
                actual.commit()

            if len(changes) > 0:
                # Changesets never seem to apply to the local copy of the database,
                # so reload the transaction table when we know there are changes
                existing_transactions = get_transactions(actual.session, start_date=datetime.datetime.now().date() - datetime.timedelta(days=30))
                existing_transaction_notes_map = {t.id: t.notes for t in existing_transactions if t.id is not None}

            time.sleep(5)

if __name__ == "__main__":
    main()
