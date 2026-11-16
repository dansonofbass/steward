"""Every category's label, word for word the web's (web/src/lib/categories.ts; import/export spec P44).
spending.LABELS covers the spending categories only; the CSV export needs all of them. tests/test_category_labels.py
reads the web file and checks they match."""
CATEGORY_LABELS: dict[str, str] = {
    "groceries": "Groceries", "dining": "Eating out", "housing": "Housing", "utilities": "Utilities",
    "transport": "Getting around", "travel": "Travel", "health": "Health", "insurance": "Insurance",
    "loan_payments": "Loan payments", "childcare_education": "Childcare and school", "giving": "Giving",
    "subscriptions": "Subscriptions", "shopping": "Shopping", "personal": "Personal", "cash_atm": "Cash and ATM",
    "kids": "Kids", "pets": "Pets", "home": "Home and garden", "gifts": "Gifts", "entertainment": "Fun",
    "income": "Income", "business_income": "Business income", "business_expense": "Business expense", "taxes": "Taxes",
    "transfer": "Transfer", "investment": "Investment activity", "fees": "Fees", "interest": "Interest",
    "reimbursement": "Reimbursement", "uncategorized": "Not sorted yet",
}


def label(key: str) -> str:
    return CATEGORY_LABELS.get(key, key)
