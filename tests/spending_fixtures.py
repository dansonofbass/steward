"""A household for the Spending tests: six complete months, April to September 2026 (history starts April 1), and
October so far, seen on October 25. Figures are made up."""
from datetime import date, datetime, timezone

from steward.db.models import SpendingTarget
from tests.factories import make_account, make_txn

TODAY = date(2026, 10, 25)
MONTHS = (4, 5, 6, 7, 8, 9)
DINING = (41_000, 62_000, 38_000, 44_000, 47_000, 51_000)       # typical 46,000 (the median, $455, half up)
SHOPPING = (39_000, 45_000, 41_000, 39_000, 43_000, 39_000)     # over $400 in 3 of 6; typical 40,000
UTILITIES = (43_000, 52_000, 41_000, 36_000, 38_000, 41_000)    # varies; typical 41,000
AT = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


def household(db) -> dict:
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit")
    for i, m in enumerate(MONTHS):
        make_txn(db, chk, date(2026, m, 1), -268_000, "HOMELOAN", merchant="Home loan", category="housing")
        make_txn(db, chk, date(2026, m, 1), 512_000, "PAYROLL", merchant="Acme payroll", category="income")
        make_txn(db, card, date(2026, m, 3), -12_000, "STREAMFLIX", merchant="Streamflix", category="subscriptions")
        make_txn(db, card, date(2026, m, 6), -124_000, "GREENLEAF", merchant="Greenleaf Market", category="groceries")
        make_txn(db, card, date(2026, m, 8), -SHOPPING[i], "MEGAMART", merchant="Megamart", category="shopping")
        make_txn(db, card, date(2026, m, 9), -9_000, "GYMTIME", merchant="Gymtime", category="personal")
        make_txn(db, card, date(2026, m, 10), -DINING[i], "NOODLE HOUSE", merchant="Noodle House", category="dining")
        make_txn(db, chk, date(2026, m, 12), -UTILITIES[i], "CITY POWER", merchant="City Power", category="utilities")
    o = (2026, 10)
    make_txn(db, chk, date(*o, 1), -268_000, "HOMELOAN", merchant="Home loan", category="housing")
    make_txn(db, chk, date(*o, 1), 512_000, "PAYROLL", merchant="Acme payroll", category="income")
    make_txn(db, chk, date(*o, 15), 512_000, "PAYROLL", merchant="Acme payroll", category="income")
    make_txn(db, card, date(*o, 3), -12_000, "STREAMFLIX", merchant="Streamflix", category="subscriptions")
    make_txn(db, card, date(*o, 14), -799, "STREAMBOX", merchant="StreamBox", category="subscriptions")
    make_txn(db, card, date(*o, 4), -48_184, "NOODLE HOUSE", merchant="Noodle House", category="dining")
    make_txn(db, card, date(*o, 9), 1_384, "NOODLE HOUSE REFUND", merchant="Noodle House", category="dining")
    make_txn(db, card, date(*o, 6), -104_000, "GREENLEAF", merchant="Greenleaf Market", category="groceries")
    make_txn(db, card, date(*o, 7), -51_200, "MEGAMART", merchant="Megamart", category="shopping")
    make_txn(db, card, date(*o, 9), -8_400, "GYMTIME", merchant="Gymtime", category="personal")
    make_txn(db, card, date(*o, 11), -15_000, "SQ *VENDOR 2291", category="uncategorized")
    make_txn(db, chk, date(*o, 13), -8_600, "CHECK 1042", category="uncategorized")
    make_txn(db, chk, date(*o, 16), 500, "MYSTERY CREDIT", category="uncategorized")
    make_txn(db, chk, date(*o, 20), -421_000, "COUNTY TAX", merchant="County tax collector", category="taxes")
    make_txn(db, chk, date(*o, 20), -50_000, "PAYMENT TO CARD", category="transfer")
    make_txn(db, chk, date(*o, 24), 1_400, "INTEREST", merchant="Interest", category="interest")
    for c, cents in (("groceries", 130_000), ("dining", 50_000), ("shopping", 40_000)):
        db.add(SpendingTarget(category=c, kind="everyday", monthly_cents=cents, updated_at=AT, updated_by=1))
    db.commit()
    return {"checking": chk, "card": card}
