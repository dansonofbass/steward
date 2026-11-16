"""Rules with a name, a note and an amount (P32-P35, P37, P39): an amount rule beats the plain one where it has an
opinion, a rule with no category sorts nothing but still labels, corrections pick the amount rule, spreading skips a
names-only rule and narrows by amount, the categorizer is taught plain sorting rules only, and ingest names and notes
new rows."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import CategorySource, MerchantRule, Transaction, TransactionNote
from steward.services import labels
from steward.services.categorize import household_rule
from steward.services.category_rules import example_rules, rule_out, spread
from steward.services.importers.base import ParsedRow
from steward.services.ingest import ingest_rows
from steward.services.transactions import apply_correction
from tests.factories import make_account, make_txn

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")   # P36: no note or name in an undo entry
NOW =datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)


def rule(db, pattern="PAYPAL", category="shopping", amount=None, **label):
    r = MerchantRule(pattern=pattern, merchant=pattern.title(), category=category, source=CategorySource.correction,
                     amount_cents=amount, **label)
    db.add(r)
    db.commit()
    return r


def test_generic_payees_by_the_built_in_rule_on_the_raw_text():
    assert [labels.generic_payee(r) for r in ("PAYPAL *DISNEYPLUS", "VENMO PAYMENT 1234", "ZELLE PAYMENT TO J.",
                                              "CASH APP*SAM", "AMZN MKTP US*2K4", "STREAMBOX")] == [
        "PayPal", "Venmo", "Zelle", "Cash App", "Amazon", None]


def test_a_plain_rule_sorts_as_before(db):
    rule(db)
    s = household_rule(db, "PAYPAL *DISNEYPLUS", -1399)
    assert (s.category, s.merchant) == ("shopping", "Paypal")
    assert household_rule(db, "PAYPAL *DISNEYPLUS").category == "shopping"


def test_an_amount_rule_beats_the_plain_rule_and_the_plain_one_is_the_fallback(db):
    rule(db)
    rule(db, category="subscriptions", amount=-1399)
    assert household_rule(db, "PAYPAL *DISNEYPLUS", -1399).category == "subscriptions"
    assert household_rule(db, "PAYPAL *EBAY", -999).category == "shopping"


def test_a_label_only_amount_rule_never_hides_the_plain_category(db):
    rule(db)
    rule(db, category=None, amount=-1399, nickname="Disney+")
    assert household_rule(db, "PAYPAL *DISNEYPLUS", -1399).category == "shopping"
    rule(db, pattern="VENMO PAYMENT", category=None, nickname="Rent share")      # normalize("VENMO PAYMENT 1234")
    assert household_rule(db, "VENMO PAYMENT 1234", -50_000) is None       # names only: the built-ins carry on


def test_a_correction_updates_the_amount_rule_for_its_amount_and_the_plain_rule_otherwise(db):
    acct = make_account(db)
    plain = rule(db)
    amount = rule(db, category=None, amount=-1399, nickname="Disney+")
    t1 = make_txn(db, acct, date(2026, 10, 3), -1399, "PAYPAL *DISNEYPLUS", merchant="PayPal")
    t2 = make_txn(db, acct, date(2026, 10, 4), -999, "PAYPAL *EBAY", merchant="PayPal")
    assert apply_correction(db, t1, None, "subscriptions", None, NOW) is amount
    assert apply_correction(db, t2, None, "gifts", None, NOW) is plain
    db.commit()
    assert (amount.category, amount.nickname, plain.category) == ("subscriptions", "Disney+", "gifts")   # the label stays


def test_spreading_skips_a_names_only_rule_and_narrows_by_amount(db):
    acct = make_account(db)
    names_only = rule(db, category=None, amount=-1399, nickname="Disney+")
    for d, cents in ((3, -1399), (4, -1399), (5, -999)):
        make_txn(db, acct, date(2026, 10, d), cents, "PAYPAL *X", merchant="PayPal")
    assert spread(db, names_only, NOW) == []
    names_only.category = "subscriptions"
    db.commit()
    assert len(spread(db, names_only, NOW)) == 2
    assert sorted(t.amount_cents for t in db.scalars(select(Transaction).where(Transaction.category == "subscriptions"))) == [-1399, -1399]


def test_the_categorizer_is_taught_plain_sorting_rules_only(db):
    rule(db, pattern="STREAMFLIX", category="subscriptions")
    rule(db, pattern="PAYPAL", category="shopping", amount=-1399)
    rule(db, pattern="VENMO", category=None, nickname="Rent share", note="for Dr. Alvarez")
    assert example_rules(db) == [("STREAMFLIX", "subscriptions")]


def test_a_rule_says_its_amount_its_name_and_whether_it_has_a_note_never_the_note(db):
    r = rule(db, category=None, amount=-1399, nickname="Disney+", note="for Dr. Alvarez")
    out = rule_out(r, 3)
    assert (out["amount_cents"], out["nickname"], out["has_note"], out["category"]) == (-1399, "Disney+", True, None)
    assert "Alvarez" not in str(out)


def test_ingest_names_and_notes_new_rows_by_the_rule_that_matches(db):
    acct = make_account(db)
    rule(db, category=None, amount=-1399, nickname="Disney+", note="Disney+ subscription", note_by=7, note_by_name="JR")
    rows = [ParsedRow(posted_at=date(2026, 10, 18), amount_cents=-1399, raw_description="PAYPAL *DISNEYPLUS", external_id="a"),
            ParsedRow(posted_at=date(2026, 10, 18), amount_cents=-999, raw_description="PAYPAL *EBAY", external_id="b")]
    new = ingest_rows(db, acct, rows, batch=None, now=NOW, model=None)
    db.commit()
    disney, ebay = new
    assert (disney.nickname, ebay.nickname) == ("Disney+", None)
    notes = db.scalars(select(TransactionNote)).all()
    assert [(n.transaction_id, n.author_id, n.author_name, n.body, n.created_at) for n in notes] == [
        (disney.id, 7, "JR", "Disney+ subscription", NOW)]
    assert (disney.category, ebay.category) == ("uncategorized", "uncategorized")   # names only: still for Review


def test_ingest_labels_nothing_in_an_investment_account(db):
    k401 = make_account(db, "401(k)", type="k401", owner="jr")
    rule(db, pattern="PAYPAL", category=None, nickname="Disney+")
    (t,) = ingest_rows(db, k401, [ParsedRow(posted_at=date(2026, 10, 18), amount_cents=-1399,
                                            raw_description="PAYPAL *DISNEYPLUS", external_id="c")], batch=None, now=NOW, model=None)
    assert t.nickname is None
