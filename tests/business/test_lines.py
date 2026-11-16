"""Schedule C lines (spec 5, ruling 7): every household category has a default line, money in is income unless it is
a refund, and transfers, taxes and interest are never on Schedule C."""
import pytest

from steward.business.lines import EXPENSE_LINES, LINE_BY_KEY, LINES, TXN_LINES, line_for
from steward.db.models import CATEGORIES


def test_the_lines_and_their_numbers():
    assert [(l.key, l.number) for l in LINES] == [
        ("income", "1"), ("advertising", "8"), ("car", "9"), ("contract_labor", "11"), ("insurance", "15"),
        ("legal_professional", "17"), ("office", "18"), ("supplies", "22"), ("travel", "24a"), ("meals", "24b"),
        ("utilities", "25"), ("software", "27b"), ("other", "27b"), ("home_office", "30")]
    assert "home_office" not in TXN_LINES and "income" not in EXPENSE_LINES
    assert LINE_BY_KEY["meals"].label == "Meals"


@pytest.mark.parametrize("category,amount,line", [
    ("dining", -4_500, "meals"), ("travel", -90_000, "travel"), ("transport", -6_000, "car"),
    ("subscriptions", -2_900, "software"), ("shopping", -1_000, "supplies"), ("home", -1_000, "supplies"),
    ("business_expense", -50_000, "office"), ("insurance", -9_000, "insurance"), ("utilities", -8_000, "utilities"),
    ("groceries", -3_000, "other"), ("uncategorized", -3_000, "other"),
    ("business_income", 300_000, "income"), ("income", 300_000, "income"), ("uncategorized", 300_000, "income"),
    ("subscriptions", 2_900, "software"),          # a refund lowers its own line
    ("business_income", -50_000, "income"), ("income", -50_000, "income"),   # a chargeback lowers income (M3)
    ("transfer", -5_000, None), ("taxes", -400_000, None), ("interest", 120, None),
])
def test_default_lines(category, amount, line):
    assert line_for(category, amount) == line


def test_a_chosen_line_wins_and_every_category_has_an_answer():
    assert line_for("dining", -4_500, "travel") == "travel"
    for c in CATEGORIES:
        assert line_for(c, -100) in (*TXN_LINES, None)
        assert line_for(c, 100) in (*TXN_LINES, None)



def test_reimbursement_is_on_no_schedule_c_line():
    assert line_for("reimbursement", 50_000) is None and line_for("reimbursement", -100) is None
