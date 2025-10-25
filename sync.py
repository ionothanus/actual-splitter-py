import time
import os
from sqlmodel import Session
from actual import Actual, Changeset, Transactions
from actual.queries import get_transactions, get_payee, get_account, create_transaction
from dotenv import load_dotenv

load_dotenv()

env_baseurl = os.getenv("ACTUAL_BASEURL")
env_password = os.getenv("ACTUAL_PASSWORD")
env_budget = os.getenv("ACTUAL_BUDGET")
env_splitterpayeeid = os.getenv("ACTUAL_SPLITTER_PAYEE_ID")
env_splitteraccountid = os.getenv("ACTUAL_SPLITTER_ACCOUNT_ID")

def detect_shared_transaction(change: Changeset, session: Session, existing_transactions: set) -> Transactions | None:
    table = change.table
    if (table is not Transactions):
        return None
    if change.id in existing_transactions:
        return None
    changed_obj: Transactions = change.from_orm(session) # type: ignore
    existing_transactions.add(change.id)
    if changed_obj.notes is not None and "#shared" in changed_obj.notes:
        return changed_obj
    return None

def create_refund_transaction(original: Transactions, session: Session):
    if (original.amount is None):
        raise ValueError("Original transaction has no amount")
    
    if (original.date is None):
        raise ValueError("Original transaction has no date")
    
    if (env_splitterpayeeid is None):
        raise ValueError("Environment variable ACTUAL_SPLITTER_PAYEE_ID is not set")
    
    if (env_splitteraccountid is None):
        raise ValueError("Environment variable ACTUAL_SPLITTER_ACCOUNT_ID is not set")
    
    payee = get_payee(session, env_splitterpayeeid)
    if payee is None:
        raise ValueError(f"Payee with ID {env_splitterpayeeid} not found")
    
    account = get_account(session, env_splitteraccountid)
    if account is None:
        raise ValueError(f"Account with ID {env_splitteraccountid} not found")

    create_transaction(
        session,
        account=account,
        date=original.get_date(),
        amount=-original.get_amount()/2,
        payee=payee,
        category=original.category,
        notes=f"Split for {'unknown payee' if original.payee is None or original.payee.name is None else original.payee.name} #auto",
    )
    session.flush()

def main() -> None:
    if (env_baseurl is None) or (env_password is None) or (env_budget is None) or (env_splitterpayeeid is None):
        raise ValueError("Missing one of ACTUAL_BASEURL, ACTUAL_PASSWORD, ACTUAL_BUDGET, ACTUAL_SPLITTER_PAYEE_ID in .env")

    with Actual(base_url=env_baseurl, file=env_budget, password=env_password) as actual:
        transaction_set = {t.id for t in get_transactions(actual.session)}
        # Handle the change listener
        while True:
            changes = actual.sync()
            changed = False
            for change in changes:
                # Implement callback logic here
                original = detect_shared_transaction(change, actual.session, transaction_set)
                if original is not None:
                    create_refund_transaction(original, actual.session)
                    changed = True
                    print(f"Created refund transaction for original ID {original.id}")
            if changed:
                actual.commit()
            time.sleep(5)


if __name__ == "__main__":
    main()
