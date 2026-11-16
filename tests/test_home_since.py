"""Since you last looked (Home spec P30-P35, P43): rows Steward received after the last look and posted at most 10
days before it; pay, Bills, large charges, then groups; at most 6 lines; net worth since an earlier day from $100;
names only, never a note."""
import json
from datetime import date, datetime, timedelta, timezone

from steward.db.models import (BalanceSnapshot, CategorySource, MerchantRule, Reimburser, TransactionNote)
from steward.services import home_since as hs
from steward.services import networth
from steward.services import spending as sp
from tests.factories import make_account, make_txn

LOOK_AT = datetime(2026, 10, 27, 19, 0, tzinfo=timezone.utc)      # Tuesday Oct 27, noon in the household
LOOK = hs.Look(LOOK_AT, False)
AFTER = LOOK_AT + timedelta(hours=1)
LOOK_DAY = date(2026, 10, 27)
TODAY = date(2026, 10, 30)


def row(db, acct, cents: int, raw: str, *, merchant: str | None = None, category: str = "uncategorized",
        posted: date = LOOK_DAY, imported: datetime = AFTER):
    t = make_txn(db, acct, posted, cents, raw, merchant=merchant, category=category)
    t.imported_at = imported
    db.commit()
    return t


def kinds(db) -> dict[str, str]:
    return {c: s.kind for c, s in sp.settings(db).items()}


def lines(db, typical_out: int | None = None) -> tuple[list[dict], int]:
    return hs.since_lines(hs.new_rows(db, LOOK), kinds(db), typical_out)


def test_imported_at_the_mark_is_old_and_just_after_it_is_new(db):
    chk = make_account(db, "Checking")
    row(db, chk, -30_000, "OLD", merchant="Old shop", category="shopping", imported=LOOK_AT)
    row(db, chk, -30_000, "NEW", merchant="New shop", category="shopping", imported=LOOK_AT + timedelta(microseconds=1))
    assert [x["name"] for x in lines(db)[0]] == ["New shop"]


def test_a_row_posted_11_days_before_the_look_is_left_out(db):
    chk = make_account(db, "Checking")
    row(db, chk, -30_000, "ELEVEN", merchant="Eleven", category="shopping", posted=LOOK_DAY - timedelta(days=11))
    row(db, chk, -30_000, "TEN", merchant="Ten", category="shopping", posted=LOOK_DAY - timedelta(days=10))
    assert [x["name"] for x in lines(db)[0]] == ["Ten"]


def test_a_history_import_never_floods_since(db):
    chk = make_account(db, "Checking")
    for i in range(40):
        row(db, chk, -50_000, f"OLD {i}", merchant=f"Old {i}", category="shopping", posted=LOOK_DAY - timedelta(days=30 + 7 * i))
    assert lines(db) == ([], 0)


def test_pay_then_bills_then_large_charges_then_groups(db):
    chk = make_account(db, "Checking")
    row(db, chk, -2_200, "BEAN 1", merchant="Bean & Leaf", category="dining")
    row(db, chk, 421_200, "PAYROLL", merchant="Northwind payroll", category="income")
    row(db, chk, -9_800, "NOODLE", merchant="Noodle House", category="dining")
    row(db, chk, -18_600, "CITY POWER", merchant="City Power", category="utilities")
    row(db, chk, -34_200, "BIG BOX", merchant="Big Box Store", category="shopping")
    row(db, chk, -6_000, "TACO", merchant="Taco Cart", category="dining")
    got, more = lines(db)
    assert more == 0
    assert got == [
        {"kind": "pay", "category": "income", "name": "Northwind payroll", "n": 1, "places": 1, "cents": 421_200},
        {"kind": "bill", "category": "utilities", "name": "City Power", "n": 1, "places": 1, "cents": -18_600},
        {"kind": "large", "category": "shopping", "name": "Big Box Store", "n": 1, "places": 1, "cents": -34_200},
        {"kind": "group", "category": "dining", "name": None, "n": 3, "places": 3, "cents": -18_000},
    ]


def test_pay_from_one_payee_is_summed(db):
    chk = make_account(db, "Checking")
    row(db, chk, 200_000, "PAYROLL 1", merchant="Northwind payroll", category="income")
    row(db, chk, 210_000, "PAYROLL 2", merchant="Northwind payroll", category="income")
    assert lines(db)[0] == [{"kind": "pay", "category": "income", "name": "Northwind payroll", "n": 2, "places": 1,
                             "cents": 410_000}]


def test_a_large_charge_is_at_least_250_dollars_and_3_percent_of_the_typical_month(db):
    chk = make_account(db, "Checking")
    row(db, chk, -24_999, "A", merchant="Under", category="shopping")
    row(db, chk, -25_000, "B", merchant="At", category="shopping")
    large = lambda typical: [x["name"] for x in lines(db, typical)[0] if x["kind"] == "large"]   # noqa: E731
    assert large(None) == ["At"]                                                 # no typical month: $250
    row(db, chk, -30_000, "C", merchant="Three percent", category="personal")
    assert large(1_000_000) == ["Three percent"]                                 # 3% of $10,000 is $300


def test_a_group_needs_150_dollars_over_two_or_more_charges(db):
    chk = make_account(db, "Checking")
    row(db, chk, -7_499, "A", merchant="One", category="dining")
    row(db, chk, -7_500, "B", merchant="Two", category="dining")
    assert lines(db)[0] == []                                                    # $149.99
    row(db, chk, -1, "C", merchant="Penny", category="dining")
    assert lines(db)[0] == []                                                    # under $1 is left out, not counted
    row(db, chk, -100, "D", merchant="Dollar", category="dining")
    assert lines(db)[0][0]["cents"] == -15_099
    row(db, chk, -20_000, "E", merchant="Alone", category="personal")
    assert [x["category"] for x in lines(db)[0]] == ["dining"]                   # one row is never a group


def test_one_payee_reads_charges_and_more_read_places(db):
    chk = make_account(db, "Checking")
    for raw in ("BEAN 1", "BEAN 2"):
        row(db, chk, -8_000, raw, merchant="Bean & Leaf", category="dining")
    assert lines(db)[0] == [{"kind": "group", "category": "dining", "name": "Bean & Leaf", "n": 2, "places": 1,
                             "cents": -16_000}]


def test_six_lines_then_how_many_more(db):
    chk = make_account(db, "Checking")
    for i in range(8):
        row(db, chk, -(10_000 + i), f"POWER {i}", merchant=f"Power {i}", category="utilities")
    got, more = lines(db)
    assert (len(got), more) == (6, 2)
    assert [x["name"] for x in got] == ["Power 7", "Power 6", "Power 5", "Power 4", "Power 3", "Power 2"]


def test_names_prefer_the_rows_name_then_the_merchant_then_the_bank_text(db):
    chk = make_account(db, "Checking")
    named = row(db, chk, -30_000, "PAYPAL *DISNEYPLUS", merchant="PayPal", category="shopping")
    named.nickname = "Disney+"
    db.commit()
    row(db, chk, -40_000, "COSTCO 0042", merchant="Costco", category="shopping")
    row(db, chk, -50_000, "CVS PHARMACY 0042", category="shopping")
    assert [x["name"] for x in lines(db)[0]] == ["CVS Pharmacy 0042", "Costco", "Disney+"]


def test_transfers_card_payments_investments_interest_refunds_and_pennies_are_left_out(db):
    chk = make_account(db, "Checking")
    brokerage = make_account(db, "Brokerage", type="brokerage_taxable")
    row(db, chk, -90_000, "TO SAVINGS", category="transfer")
    t = row(db, chk, -80_000, "CARD PAYMENT", category="shopping")
    t.is_transfer = True
    db.commit()
    row(db, brokerage, -70_000, "BUY VTI", category="investment")
    row(db, chk, 1_400, "INTEREST", merchant="Interest", category="interest")
    row(db, chk, 5_000, "NOODLE REFUND", merchant="Noodle House", category="dining")
    row(db, chk, -99, "PENNY", merchant="Penny", category="utilities")
    row(db, chk, -60_000, "PAYROLL REVERSAL", merchant="Northwind payroll", category="income")
    assert lines(db) == ([], 0)


def test_repayments_read_as_pay_with_the_payers_name(db):
    chk = make_account(db, "Checking")
    payer = Reimburser(name="Northwind")
    db.add(payer)
    db.flush()
    t = row(db, chk, 118_400, "ACH NORTHWIND EXP", category="reimbursement")
    t.reimburser_id = payer.id
    db.commit()
    assert lines(db)[0] == [{"kind": "pay", "category": "reimbursement", "name": "Northwind", "n": 1, "places": 1,
                             "cents": 118_400}]


def test_no_note_text_ever_reaches_since(db):
    chk = make_account(db, "Checking")
    t = row(db, chk, -30_000, "STREAMBOX", merchant="StreamBox", category="shopping")
    db.add(TransactionNote(transaction_id=t.id, author_id=1, author_name="Jr", body="zorblax", created_at=AFTER))
    db.add(MerchantRule(pattern="STREAMBOX", merchant="StreamBox", category="shopping", source=CategorySource.correction,
                        note="for Dr. Alvarez", note_by=1, note_by_name="Jr"))
    db.commit()
    out = json.dumps(hs.since_view(db, LOOK, TODAY, kinds(db), None, 0))
    assert "StreamBox" in out and "zorblax" not in out and "Alvarez" not in out


def test_net_worth_since_needs_an_earlier_day_and_a_100_dollar_change(db):
    chk = make_account(db, "Checking")
    db.add(BalanceSnapshot(account_id=chk.id, as_of=LOOK_DAY, balance_cents=1_000_000))
    db.add(BalanceSnapshot(account_id=chk.id, as_of=TODAY, balance_cents=1_009_999))
    db.commit()
    now = networth.net_worth_on(db, TODAY)
    assert hs.net_worth_since(db, LOOK, TODAY, now) is None                        # $99.99
    assert hs.net_worth_since(db, LOOK, TODAY, now + 1) == 10_000                  # $100
    today_look = hs.Look(datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc), False)
    assert hs.net_worth_since(db, today_look, TODAY, now + 500_000) is None        # the same day: omitted


def test_from_day_is_the_households_day(db):
    late = hs.Look(datetime(2026, 10, 28, 6, 30, tzinfo=timezone.utc), False)      # 11:30 pm on Oct 27 in California
    got = hs.since_view(db, late, TODAY, kinds(db), None, 0)
    assert (got["from"], got["from_day"], got["over_month"]) == ("2026-10-28T06:30:00+00:00", "2026-10-27", False)


def test_a_first_visit_has_no_since_and_over_a_month_says_so(db):
    assert hs.since_view(db, None, TODAY, kinds(db), None, 0) is None
    got = hs.since_view(db, hs.Look(LOOK_AT - timedelta(days=30), True), TODAY, kinds(db), None, 0)
    assert got["over_month"] is True and got["lines"] == [] and got["more"] == 0
