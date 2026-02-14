# Actual Budget Auto-Splitter

A Python automation tool that monitors your [Actual Budget](https://actualbudget.org/) instance for new transactions and automatically creates reimbursement transactions for shared expenses.

## What it does

When you add the `#shared` tag to a transaction's notes field, this tool automatically:
1. Detects the tagged transaction
2. Creates a reimbursement transaction for half the amount, associated with the configured payee and account
3. Tags the reimbursement transaction with `#auto` for easy identification
4. Optionally creates a corresponding expense in [Spliit](https://spliit.app) for tracking shared expenses with your partner

This is a useful companion to expense-splitting apps like Spliit, Splitwise, or Tricount, for couples or roommates who split expenses in half by default.

## Features

- Real-time monitoring of budget changes via Actual's sync API
- Automatic creation of 50/50 split transactions
- Configurable target account and payee for reimbursement deposit transactions
- Preserves original transaction category on the reimbursement deposit transactions
- Optional [Spliit](https://spliit.app) integration:
  - Automatically create Spliit expenses when you tag transactions with `#shared`
  - Automatically create Actual transactions when your partner adds expenses in Spliit

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

# Optional: Spliit integration
SPLIIT_BASE_URL="https://spliit.app"  # Or your self-hosted instance
SPLIIT_GROUP_ID="your-group-id"
SPLIIT_PAYER_ID="your-participant-id"
```

## Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `ACTUAL_BASEURL` | URL of your Actual Budget server | `https://actual.example.com` |
| `ACTUAL_PASSWORD` | Your Actual Budget password | `password123` |
| `ACTUAL_BUDGET` | Name of your budget file | `Budget` |
| `ACTUAL_SPLITTER_PAYEE_ID` | Payee name for refund transactions | `Adrian` |
| `ACTUAL_SPLITTER_ACCOUNT_ID` | Account name where refunds are posted | `Chequing` |
| `ACTUAL_POLL_INTERVAL` | Seconds between Actual Budget sync polls (default: 5) | `5` |
| `ACTUAL_TRIGGER_TAG` | Tag in transaction notes that triggers splitting (default: `#shared`) | `#shared` |
| `LOGGING_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) | `INFO` |

### Spliit Integration (Optional)

| Variable | Description | Example |
|----------|-------------|---------|
| `SPLIIT_BASE_URL` | URL of your Spliit instance (defaults to https://spliit.app) | `https://spliit.app` |
| `SPLIIT_GROUP_ID` | The ID of your Spliit group (from the URL) | `aBcDeFgHiJk` |
| `SPLIIT_PAYER_ID` | Your participant ID in the Spliit group | `xYz123AbC` |
| `SPLIIT_POLL_INTERVAL` | Seconds between Spliit expense polls (default: 30) | `30` |
| `SPLIIT_CATEGORY_MAPPING_FILE` | Path to category mapping JSON file (default: `category-mapping.json`) | `category-mapping.json` |

#### Category Mapping

Category mapping works **bidirectionally**:
- **Spliit → Actual**: When expenses are synced from Spliit, the Spliit category is mapped to an Actual category
- **Actual → Spliit**: When you tag a transaction with `#shared`, the Actual category is mapped to a Spliit category

The mapping is defined in a JSON file (default: `category-mapping.json`). Copy the example file to get started:

```bash
cp category-mapping.example.json category-mapping.json
```

**Format:**
```json
{
  "Groceries": "Food",
  "Dining Out": "Restaurants",
  "Gas/Fuel": "Auto & Transport",
  "Electricity": "Utilities"
}
```

Keys are Spliit category names, values are Actual category names.

**Spliit category names** can be specified as:
- Just the category name: `Groceries`, `Dining Out`, `Gas/Fuel`
- Full path with grouping: `Food and Drink/Groceries`, `Transportation/Gas/Fuel`

**Available Spliit categories:**

| Grouping | Categories |
|----------|------------|
| Uncategorized | General, Payment |
| Entertainment | Entertainment, Games, Movies, Music, Sports |
| Food and Drink | Food and Drink, Dining Out, Groceries, Liquor |
| Home | Home, Electronics, Furniture, Household Supplies, Maintenance, Mortgage, Pets, Rent, Services |
| Life | Childcare, Clothing, Donation, Education, Gifts, Insurance, Medical Expenses, Taxes |
| Transportation | Transportation, Bicycle, Bus/Train, Car, Gas/Fuel, Hotel, Parking, Plane, Taxi |
| Utilities | Utilities, Cleaning, Electricity, Heat/Gas, Trash, TV/Phone/Internet, Water |

The mapping is bidirectional - when you tag an Actual transaction categorized as "Food" with `#shared`, the expense created in Spliit will be categorized as "Groceries".

**Note on Actual → Spliit mapping:** If multiple Spliit categories map to the same Actual category, the first occurrence in the JSON file is used. For example, if your mapping contains both `"Groceries": "Food"` and `"Dining Out": "Food"`, an Actual transaction categorized as "Food" will be mapped to Spliit's "Groceries" category (whichever appears first in the file).

To find your Spliit group ID and participant ID:
1. Open your group in Spliit
2. The group ID is in the URL: `https://spliit.app/groups/{GROUP_ID}`
3. Open browser developer tools (F12), go to the Network tab
4. Click on any expense or refresh the page
5. Look for a request to `/api/trpc/groups.get` - the response will contain participant IDs

## Usage

Run the sync script:
```bash
python sync.py
```

The script will:
1. Connect to your Actual Budget server
2. Monitor for changes every 5 seconds
3. Automatically create deposit transactions when you add `#shared` to a transaction's notes
4. If Spliit is configured, poll for new expenses and create corresponding Actual transactions

### Example Workflow

1. You pay for a shared dinner at Food Restaurant: $60.00
2. Enter that transaction, adding `#shared` to the transaction notes when you create it
3. The tool automatically creates a deposit transaction:
   - Account: Your configured account (e.g., "Chequing")
   - Payee: Your configured payee (e.g., "Adrian")
   - Amount: -$30.00 (half of the original)
   - Category: Same as the original transaction
   - Notes: "Food Restaurant #auto"
4. If Spliit is configured, an expense is also created in your Spliit group:
   - Title: "Food Restaurant"
   - Amount: $60.00 (full amount)
   - Paid by: You
   - Split: Evenly between all group participants

### Reverse Sync: Spliit to Actual

When your partner adds an expense in Spliit (that you didn't pay for), the tool automatically creates a corresponding transaction in Actual:

1. Your partner pays for groceries: $80.00 and adds it to Spliit
2. The tool detects the new Spliit expense
3. An Actual transaction is created:
   - Account: Your configured splitter account
   - Payee: Your configured splitter payee
   - Amount: -$40.00 (your share, as an expense)
   - Notes: "Groceries (paid by Partner) #spliit"

This keeps your Actual budget in sync with shared expenses your partner tracks in Spliit.

## Known Limitations

- Currently only supports 50/50 splits (not configurable ratios)
- Editing transactions is not currently supported: the #shared tag must be included during the creation of the transaction, and changes after creation will not update the automatically-created deposit transaction
- Requires the script to be running continuously to detect changes

## License

See repository license file for details.

## Acknowledgments

Built with [actualpy](https://github.com/bvanelli/actualpy), the Python library for Actual Budget.
