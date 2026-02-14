"""
Main synchronization script for Actual Budget and Spliit integration.
"""

import time
import datetime
import os
import logging
import threading
from sys import stdout

from actual import Actual, Transactions
from actual.queries import get_transactions
from dotenv import load_dotenv

from spliit import create_spliit_client_from_env, SpliitClient
from actual_helpers import (
    detect_new_shared_transaction,
    create_deposit_transaction,
)
from category_mapping import load_category_mapping
from spliit_helpers import create_spliit_expense, process_spliit_expenses

load_dotenv()

# Environment variables
env_baseurl = os.getenv("ACTUAL_BASEURL")
env_password = os.getenv("ACTUAL_PASSWORD")
env_budget = os.getenv("ACTUAL_BUDGET")
env_splitter_payee = os.getenv("ACTUAL_SPLITTER_PAYEE_ID")
env_splitter_account = os.getenv("ACTUAL_SPLITTER_ACCOUNT_ID")
env_logging_level = os.getenv("LOGGING_LEVEL", "INFO").upper()
env_actual_poll_interval = int(os.getenv("ACTUAL_POLL_INTERVAL", "5"))
env_spliit_poll_interval = int(os.getenv("SPLIIT_POLL_INTERVAL", "30"))
env_category_mapping_file = os.getenv("SPLIIT_CATEGORY_MAPPING_FILE", "category-mapping.json")
env_trigger_tag = os.getenv("ACTUAL_TRIGGER_TAG", "#shared")

# Configure logging
logger = logging.getLogger(__name__)
logging.getLogger().addHandler(logging.StreamHandler(stdout))
logger.setLevel(env_logging_level)

# Load category mapping from file at startup
category_mapping = load_category_mapping(env_category_mapping_file)
if category_mapping:
    logger.info(f"Loaded {len(category_mapping)} category mappings from {env_category_mapping_file}")


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
    if env_splitter_payee is None or env_splitter_account is None:
        logger.error("ACTUAL_SPLITTER_PAYEE_ID and ACTUAL_SPLITTER_ACCOUNT_ID must be set")
        return

    # Only load the last month of transactions for performance reasons
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

                    # Deleted transactions are ignored
                    if changed_columns.get("tombstone"):
                        continue

                    # Only process new transactions
                    if change.id in transaction_ids:
                        continue

                    transaction_ids.add(change.id)

                    original = detect_new_shared_transaction(
                        change,
                        changed_columns,
                        actual.session,
                        existing_transaction_notes_map,
                        env_trigger_tag,
                    )
                    if original is not None:
                        local_changes = True
                        create_deposit_transaction(
                            original,
                            changed_columns,
                            actual.session,
                            env_splitter_payee,
                            env_splitter_account,
                        )
                        logger.info(f"Created deposit transaction for original ID {original.id}")

                        # Also create expense in Spliit if configured
                        if spliit_client:
                            try:
                                create_spliit_expense(
                                    original,
                                    changed_columns,
                                    spliit_client,
                                    actual.session,
                                    category_mapping,
                                )
                            except Exception as e:
                                logger.error(f"Failed to create Spliit expense: {e}")

                if local_changes:
                    actual.commit()

                if len(changes) > 0:
                    # Changesets don't apply to the local database copy,
                    # so reload the transaction table when there are changes
                    existing_transactions = get_transactions(
                        actual.session,
                        start_date=datetime.datetime.now().date() - datetime.timedelta(days=30),
                    )
                    existing_transaction_notes_map = {
                        t.id: t.notes for t in existing_transactions if t.id is not None
                    }

        except Exception as e:
            logger.error(f"Error in Actual polling loop: {e}")

        # Use wait() instead of sleep() so we wake up immediately on stop_event
        stop_event.wait(env_actual_poll_interval)


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
    if env_splitter_payee is None or env_splitter_account is None:
        logger.error("ACTUAL_SPLITTER_PAYEE_ID and ACTUAL_SPLITTER_ACCOUNT_ID must be set")
        return

    while not stop_event.is_set():
        try:
            logger.debug("Polling Spliit for new expenses...")
            with lock:
                if process_spliit_expenses(
                    spliit_client,
                    actual.session,
                    processed_spliit_ids,
                    category_mapping,
                    env_splitter_payee,
                    env_splitter_account,
                ):
                    actual.commit()
        except Exception as e:
            logger.error(f"Failed to process Spliit expenses: {e}")

        # Use wait() instead of sleep() so we wake up immediately on stop_event
        stop_event.wait(env_spliit_poll_interval)


def main() -> None:
    if env_baseurl is None or env_password is None or env_budget is None or env_splitter_payee is None:
        raise ValueError(
            "Missing one of ACTUAL_BASEURL, ACTUAL_PASSWORD, ACTUAL_BUDGET, ACTUAL_SPLITTER_PAYEE_ID in .env"
        )

    # Initialize Spliit client (optional)
    spliit_client = create_spliit_client_from_env()
    if spliit_client:
        logger.info("Spliit integration enabled")
    else:
        logger.info("Spliit integration disabled (SPLIIT_GROUP_ID and SPLIIT_PAYER_ID not set)")

    with Actual(base_url=env_baseurl, file=env_budget, password=env_password) as actual:
        lock = threading.Lock()
        stop_event = threading.Event()

        # Track processed Spliit expense IDs to avoid duplicates
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
