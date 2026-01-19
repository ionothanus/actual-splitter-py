# Actual Budget Auto-Splitter

A Python automation tool that monitors your [Actual Budget](https://actualbudget.org/) instance for new transactions and automatically creates reimbursement transactions for shared expenses.

## What it does

When you add the `#shared` tag to a transaction's notes field, this tool automatically:
1. Detects the tagged transaction
2. Creates a reimbursement transaction for half the amount, associated with the configured payee and account
3. Tags the reimbursement transaction with `#auto` for easy identification

This is a useful companion to tools like Splitwise or Tricount, for couples or roommates who split expenses in half by default.

## Features

- Real-time monitoring of budget changes via Actual's sync API
- Automatic creation of 50/50 split transactions
- Configurable target account and payee for reimbursement deposit transactions
- Preserves original transaction category on the reimbursement deposit transactions

## Requirements

- Python 3.14+
- An [Actual Budget](https://actualbudget.org/) server instance
- API access to your Actual Budget server

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd actual-rule-py
```

2. Create a virtual environment and activate it:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy the example environment file and configure it:
```bash
cp .env.example .env
```

5. Edit [.env](.env) with your Actual Budget details:
```env
ACTUAL_BASEURL=https://your-actual-instance.com
ACTUAL_PASSWORD="your-password"
ACTUAL_BUDGET="Your Budget Name"
ACTUAL_SPLITTER_PAYEE_ID="Partner Name"
ACTUAL_SPLITTER_ACCOUNT_ID="Target Account"
LOGGING_LEVEL="INFO"
```

## Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `ACTUAL_BASEURL` | URL of your Actual Budget server | `https://actual.example.com` |
| `ACTUAL_PASSWORD` | Your Actual Budget password | `password123` |
| `ACTUAL_BUDGET` | Name of your budget file | `Budget` |
| `ACTUAL_SPLITTER_PAYEE_ID` | Payee name for refund transactions | `Adrian` |
| `ACTUAL_SPLITTER_ACCOUNT_ID` | Account name where refunds are posted | `Chequing` |
| `LOGGING_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) | `INFO` |

## Usage

Run the sync script:
```bash
python sync.py
```

The script will:
1. Connect to your Actual Budget server
2. Monitor for changes every 5 seconds
3. Automatically create deposit transactions when you add `#shared` to a transaction's notes

### Example Workflow

1. You pay for a shared dinner at Food Restaurant: $60.00
2. Enter that transaction, adding `#shared` to the transaction notes when you create it
3. The tool automatically creates a deposit transaction:
   - Account: Your configured account (e.g., "Chequing")
   - Payee: Your configured payee (e.g., "Adrian")
   - Amount: -$30.00 (half of the original)
   - Category: Same as the original transaction
   - Notes: "Food Restaurant #auto"

## Known Limitations

- Currently only supports 50/50 splits (not configurable ratios)
- Editing transactions is not currently supported: the #shared tag must be included during the creation of the transaction, and changes after creation will not update the automatically-created deposit transaction
- Requires the script to be running continuously to detect changes

## License

See repository license file for details.

## Acknowledgments

Built with [actualpy](https://github.com/bvanelli/actualpy), the Python library for Actual Budget.
