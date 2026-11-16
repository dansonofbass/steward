"""Schedule C lines (spec 5; ruling 7). Numbers from the 2025 Schedule C instructions,
https://www.irs.gov/instructions/i1040sc. Software and Other both report on line 27b (Part V, line 48)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    key: str
    number: str
    label: str


LINES: tuple[Line, ...] = (
    Line("income", "1", "Income"),
    Line("advertising", "8", "Advertising"),
    Line("car", "9", "Car"),
    Line("contract_labor", "11", "Contract labor"),
    Line("insurance", "15", "Insurance"),
    Line("legal_professional", "17", "Legal and professional"),
    Line("office", "18", "Office"),
    Line("supplies", "22", "Supplies"),
    Line("travel", "24a", "Travel"),
    Line("meals", "24b", "Meals"),
    Line("utilities", "25", "Utilities"),
    Line("software", "27b", "Software"),
    Line("other", "27b", "Other"),
    Line("home_office", "30", "Home office"),
)
LINE_BY_KEY: dict[str, Line] = {l.key: l for l in LINES}
TXN_LINES: tuple[str, ...] = tuple(l.key for l in LINES if l.key != "home_office")
EXPENSE_LINES: tuple[str, ...] = tuple(l.key for l in LINES if l.key != "income")
NOT_SCHEDULE_C = frozenset({"transfer", "taxes", "interest", "reimbursement"})   # reimbursable spec: neither income nor spending
INCOME_CATEGORIES = frozenset({"income", "business_income", "gifts", "uncategorized"})
EARNED = frozenset({"income", "business_income"})       # money out under these lowers income (final review M3)
CATEGORY_LINE: dict[str, str] = {
    "dining": "meals", "travel": "travel", "transport": "car", "insurance": "insurance", "utilities": "utilities",
    "subscriptions": "software", "shopping": "supplies", "home": "supplies", "business_expense": "office",
}


def line_for(category: str, amount_cents: int, chosen: str | None = None) -> str | None:
    """The Schedule C line a business row reports on: the line a person chose, else the category's default. Money in
    under an income-like category is income, and money out under income or business income (a chargeback) lowers it;
    money in under a spending category is a refund on that line. None means the row isn't on Schedule C at all
    (transfers, taxes, interest)."""
    if chosen:
        return chosen
    if category in NOT_SCHEDULE_C:
        return None
    if amount_cents > 0 and category in INCOME_CATEGORIES or category in EARNED:
        return "income"
    return CATEGORY_LINE.get(category, "other")

