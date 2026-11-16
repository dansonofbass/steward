"""Business rules (spec 5; rulings 3-4): new rows are tagged at import, a rule re-tags earlier rows that no person
decided, specific beats broad, and removing a rule leaves rows as they are (Review Focus 2)."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.business.rules import RuleError, RuleSet, add_rule, remove_rule
from steward.business.tagging import set_business
from steward.db.models import BusinessRule, Owner, Transaction
from steward.deps import now
from steward.services.importers.base import ParsedRow
from steward.services.ingest import ingest_rows
from tests.factories import make_account, make_txn

AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def rule(db, kind, *, txn=None, account=None, pct=100, line=None):
    r, n = add_rule(db, kind=kind, txn=txn, account=account, pct=pct, line=line, user_id=1, at=AT)
    db.commit()
    return r, n


def test_a_rule_tags_new_transactions_at_import(db):
    card = make_account(db, "Rewards Card", type="credit")
    seed = make_txn(db, card, date(2026, 9, 3), -2_900, "NOTEFLOW PRO 0912", merchant="Noteflow")
    rule(db, "merchant", txn=seed, pct=100, line="software")
    new = ingest_rows(db, card, [ParsedRow(date(2026, 10, 3), -2_900, "NOTEFLOW PRO 1003", "n1"),
                                 ParsedRow(date(2026, 10, 4), -4_100, "HARBOR GRILL", "n2")], batch=None, now=now(),
                      model=None)
    assert [(t.business_pct, t.business_source, t.business_line, t.is_business) for t in new] == [
        (100, "rule", "software", True), (0, "none", None, False)]


def test_a_merchant_rule_is_for_its_account_only_and_a_split_rule_splits(db):
    card = make_account(db, "Rewards Card", type="credit")
    chk = make_account(db, "Checking")
    seed = make_txn(db, card, date(2026, 9, 1), -10_000, "MOBILE ONE WIRELESS", category="utilities")
    rule(db, "merchant", txn=seed, pct=40)
    rows = [ParsedRow(date(2026, 10, 1), -10_000, "MOBILE ONE WIRELESS", "m1")]
    assert ingest_rows(db, card, rows, batch=None, now=now(), model=None)[0].business_pct == 40
    rows = [ParsedRow(date(2026, 10, 1), -10_000, "MOBILE ONE WIRELESS", "m2")]
    assert ingest_rows(db, chk, rows, batch=None, now=now(), model=None)[0].business_pct == 0


def test_a_client_rule_is_for_money_in_on_any_account(db):
    chk = make_account(db, "Checking")
    pay = make_txn(db, chk, date(2026, 9, 1), 300_000, "ACH CLIENT INV 4821", category="business_income")
    r, n = rule(db, "client", txn=pay)
    assert (r.pattern, r.pct, n) == ("ACH CLIENT INV", 100, 1)
    new = ingest_rows(db, make_account(db, "Savings", type="savings"),
                      [ParsedRow(date(2026, 10, 1), 450_000, "ACH CLIENT INV 5003", "c1"),
                       ParsedRow(date(2026, 10, 2), -5_000, "ACH CLIENT INV 5004", "c2")], batch=None, now=now(),
                      model=None)
    assert [t.business_pct for t in new] == [100, 0]
    out = make_txn(db, chk, date(2026, 9, 2), -5_000, "HARBOR GRILL")
    with pytest.raises(RuleError) as e:
        rule(db, "client", txn=out)
    assert str(e.value) == "A client is someone who pays you, so choose money coming in."


def test_a_rule_never_overrides_a_persons_own_choice_and_specific_beats_broad(db):
    bchk = make_account(db, "Business checking", type="business_checking", owner=Owner.business)
    mine = make_txn(db, bchk, date(2026, 9, 1), -6_000, "HARBOR GRILL")            # tagged personal by hand
    set_business(mine, 0, source="manual"); db.commit()
    split = make_txn(db, bchk, date(2026, 9, 2), -10_000, "MOBILE ONE WIRELESS")
    set_business(split, 30, source="manual"); db.commit()
    free = make_txn(db, bchk, date(2026, 9, 3), -9_000, "CLOUDHOST INC")
    phone = make_txn(db, bchk, date(2026, 9, 4), -10_000, "MOBILE ONE WIRELESS")
    xfer = make_txn(db, bchk, date(2026, 9, 5), -50_000, "OWNER DRAW", category="transfer", is_transfer=True)
    _, n = rule(db, "merchant", txn=phone, pct=50)
    assert n == 1                                                   # phone only: the split one is a person's choice
    _, n = rule(db, "account", account=bchk, pct=100)
    db.refresh(mine); db.refresh(split); db.refresh(free); db.refresh(phone); db.refresh(xfer)
    assert n == 1 and free.business_pct == 100 and free.business_source == "rule"
    assert (mine.business_pct, mine.business_source) == (0, "manual")
    assert (split.business_pct, split.business_source) == (30, "manual")
    assert phone.business_pct == 50                                 # the merchant rule beats the whole account
    assert xfer.business_pct == 0                                   # transfers are never tagged
    r = db.scalar(select(BusinessRule).where(BusinessRule.kind == "account"))
    assert remove_rule(db, r.id) is True and remove_rule(db, r.id) is False
    db.commit(); db.refresh(free)
    assert free.business_pct == 100                                 # removing a rule leaves rows as they are


def test_the_same_rule_twice_updates_it(db):
    card = make_account(db, "Rewards Card", type="credit")
    t = make_txn(db, card, date(2026, 9, 1), -10_000, "MOBILE ONE WIRELESS")
    a, _ = rule(db, "merchant", txn=t, pct=40)
    b, _ = rule(db, "merchant", txn=t, pct=60, line="utilities")
    assert a.id == b.id and (b.pct, b.line) == (60, "utilities")
    assert db.scalar(select(BusinessRule).where(BusinessRule.id == a.id)).pct == 60


@pytest.mark.parametrize("kw,message", [
    ({"kind": "merchant", "pct": 0}, "Choose a whole percent from 1 to 100."),
    ({"kind": "merchant", "pct": 50, "line": "yacht"}, "That isn't one of the Schedule C lines."),
    ({"kind": "planet", "pct": 50}, "Choose a merchant, a client or a whole account."),
])
def test_rule_refusals(db, kw, message):
    t = make_txn(db, make_account(db), date(2026, 9, 1), -1_000, "HARBOR GRILL")
    with pytest.raises(RuleError) as e:
        add_rule(db, txn=t, account=None, user_id=1, at=AT, **{"line": None, **kw})
    assert str(e.value) == message


def test_ruleset_order(db):
    card = make_account(db, "Card", type="credit")
    t = make_txn(db, card, date(2026, 9, 1), 5_000, "ACH CLIENT INV 1")
    rule(db, "client", txn=t)
    rule(db, "account", account=card, pct=20)
    rs = RuleSet.load(db)
    assert rs.business_for(card.id, "ACH CLIENT INV 9", 5_000, legacy=None, owner_business=False)[0] == 100
    assert rs.business_for(card.id, "SOMETHING", -5_000, legacy=None, owner_business=False) == (20, "rule", None)
    other = make_account(db, "Checking")
    assert rs.business_for(other.id, "SOMETHING", -5_000, legacy=True, owner_business=False) == (100, "rule", None)
    assert rs.business_for(other.id, "SOMETHING", -5_000, legacy=None, owner_business=True) == (100, "account", None)
    assert rs.business_for(other.id, "SOMETHING", -5_000, legacy=None, owner_business=False) == (0, "none", None)
    # an old "not business" merchant rule beats a Business-owned account
    assert rs.business_for(other.id, "SOMETHING", -5_000, legacy=False, owner_business=True) == (0, "none", None)


def test_a_client_rule_puts_every_payment_on_the_income_line_at_100_percent(db):
    """Final review M2: a client payment the categorizer put under a spending category is still income."""
    chk = make_account(db, "Checking", type="checking", owner=Owner.jr)
    pay = make_txn(db, chk, date(2026, 9, 3), 120_000, "ACH CLIENT INV 4821", category="shopping")
    later = make_txn(db, chk, date(2026, 9, 20), 80_000, "ACH CLIENT INV 4821", category="shopping")
    r, n = rule(db, "client", txn=pay, pct=40, line="supplies")
    db.refresh(later)
    assert (r.pct, r.line, n) == (100, "income", 2)
    assert (later.business_pct, later.business_line, later.business_source) == (100, "income", "rule")
